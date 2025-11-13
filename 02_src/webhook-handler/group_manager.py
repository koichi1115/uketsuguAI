"""
グループLINE管理モジュール
Phase 2: グループチャット機能
"""
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timezone
import sqlalchemy
from sqlalchemy import text


class GroupManager:
    """グループチャット機能の管理"""

    def __init__(self, engine: sqlalchemy.engine.Engine):
        """
        Args:
            engine: SQLAlchemy Engineインスタンス
        """
        self.engine = engine

    def can_add_group(self, owner_user_id: str) -> Tuple[bool, Optional[str]]:
        """
        ユーザーがグループを追加できるかチェック

        Args:
            owner_user_id: マスタアカウントのuser_id

        Returns:
            (追加可能か, エラーメッセージ)
        """
        with self.engine.connect() as conn:
            # 1. プロフィール登録チェック
            profile = conn.execute(
                text("""
                    SELECT relationship, prefecture, municipality, death_date
                    FROM user_profiles
                    WHERE user_id = :user_id
                """),
                {"user_id": owner_user_id}
            ).fetchone()

            if not profile or not all(profile):
                return False, "❌ グループ追加には、まずプロフィール登録を完了してください。"

            # 2. 有料プラン確認
            subscription = conn.execute(
                text("""
                    SELECT plan_type, status, group_enabled
                    FROM subscriptions
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"user_id": owner_user_id}
            ).fetchone()

            if not subscription:
                return False, "❌ グループ追加は有料プラン限定機能です。\n\n「アップグレード」と入力してプランをご確認ください。"

            plan_type, status, group_enabled = subscription

            if status != 'active':
                return False, "❌ グループ追加は有料プラン限定機能です。\n\n「アップグレード」と入力してプランをご確認ください。"

            if plan_type not in ['beta', 'standard']:
                return False, "❌ グループ追加は有料プラン限定機能です。\n\n「アップグレード」と入力してプランをご確認ください。"

            # 3. 既存グループ数チェック（1件まで）
            group_count = conn.execute(
                text("""
                    SELECT COUNT(*)
                    FROM groups
                    WHERE owner_user_id = :user_id AND is_deleted = false
                """),
                {"user_id": owner_user_id}
            ).scalar()

            if group_count >= 1:
                return False, "⚠️ 有料プランで追加できるグループは1件までです。\n\n既存のグループを削除してから追加してください。"

            return True, None

    def create_group(
        self,
        line_group_id: str,
        owner_user_id: str,
        group_name: Optional[str] = None
    ) -> Optional[str]:
        """
        グループを作成

        Args:
            line_group_id: LINE Group ID
            owner_user_id: マスタアカウントのuser_id
            group_name: グループ名

        Returns:
            作成されたgroup_id、失敗時はNone
        """
        with self.engine.connect() as conn:
            with conn.begin():
                # グループ作成
                result = conn.execute(
                    text("""
                        INSERT INTO groups (line_group_id, owner_user_id, group_name, status)
                        VALUES (:line_group_id, :owner_user_id, :group_name, 'active')
                        RETURNING id
                    """),
                    {
                        "line_group_id": line_group_id,
                        "owner_user_id": owner_user_id,
                        "group_name": group_name or "受け継ぐAIグループ"
                    }
                )
                group_id = result.fetchone()[0]

                # マスタアカウントのタスクをグループタスクとして複製
                conn.execute(
                    text("""
                        INSERT INTO tasks (
                            group_id, title, description, category,
                            priority, due_date, status, order_index,
                            generation_step, tips, source_type
                        )
                        SELECT
                            :group_id, title, description, category,
                            priority, due_date, 'pending', order_index,
                            generation_step, tips, source_type
                        FROM tasks
                        WHERE user_id = :user_id AND is_deleted = false
                    """),
                    {
                        "group_id": str(group_id),
                        "user_id": owner_user_id
                    }
                )

                print(f"✅ グループ作成: group_id={group_id}, line_group_id={line_group_id}")
                return str(group_id)

    def get_group_by_line_id(self, line_group_id: str) -> Optional[Dict]:
        """
        LINE Group IDからグループ情報を取得

        Args:
            line_group_id: LINE Group ID

        Returns:
            グループ情報、存在しない場合はNone
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, owner_user_id, group_name, status
                    FROM groups
                    WHERE line_group_id = :line_group_id AND is_deleted = false
                """),
                {"line_group_id": line_group_id}
            ).fetchone()

            if not result:
                return None

            return {
                "id": str(result[0]),
                "owner_user_id": str(result[1]),
                "group_name": result[2],
                "status": result[3]
            }

    def add_member(
        self,
        group_id: str,
        line_user_id: str,
        display_name: Optional[str] = None
    ) -> None:
        """
        グループメンバーを追加

        Args:
            group_id: グループID
            line_user_id: メンバーのLINE User ID
            display_name: メンバーの表示名
        """
        with self.engine.connect() as conn:
            with conn.begin():
                # 既存メンバーをチェック
                existing = conn.execute(
                    text("""
                        SELECT id, is_active
                        FROM group_members
                        WHERE group_id = :group_id AND line_user_id = :line_user_id
                    """),
                    {"group_id": group_id, "line_user_id": line_user_id}
                ).fetchone()

                if existing:
                    # 既存メンバーを再アクティブ化
                    conn.execute(
                        text("""
                            UPDATE group_members
                            SET is_active = true,
                                display_name = :display_name,
                                left_at = NULL,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = :id
                        """),
                        {"id": str(existing[0]), "display_name": display_name}
                    )
                else:
                    # 新規メンバー追加
                    conn.execute(
                        text("""
                            INSERT INTO group_members (group_id, line_user_id, display_name, is_active)
                            VALUES (:group_id, :line_user_id, :display_name, true)
                        """),
                        {
                            "group_id": group_id,
                            "line_user_id": line_user_id,
                            "display_name": display_name
                        }
                    )

                print(f"✅ メンバー追加: group_id={group_id}, line_user_id={line_user_id}")

    def remove_member(self, group_id: str, line_user_id: str) -> None:
        """
        グループメンバーを削除

        Args:
            group_id: グループID
            line_user_id: メンバーのLINE User ID
        """
        with self.engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("""
                        UPDATE group_members
                        SET is_active = false,
                            left_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE group_id = :group_id AND line_user_id = :line_user_id
                    """),
                    {"group_id": group_id, "line_user_id": line_user_id}
                )

                print(f"✅ メンバー削除: group_id={group_id}, line_user_id={line_user_id}")

    def get_group_members(self, group_id: str) -> List[Dict]:
        """
        グループメンバー一覧を取得

        Args:
            group_id: グループID

        Returns:
            メンバー情報のリスト
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT line_user_id, display_name
                    FROM group_members
                    WHERE group_id = :group_id AND is_active = true
                    ORDER BY joined_at
                """),
                {"group_id": group_id}
            )

            members = []
            for row in result:
                members.append({
                    "line_user_id": row[0],
                    "display_name": row[1] or "メンバー"
                })

            return members

    def assign_task(
        self,
        task_id: str,
        line_user_id: str,
        display_name: Optional[str] = None
    ) -> bool:
        """
        タスクを担当者に割り当て

        Args:
            task_id: タスクID
            line_user_id: 担当者のLINE User ID
            display_name: 担当者の表示名

        Returns:
            成功したらTrue
        """
        with self.engine.connect() as conn:
            with conn.begin():
                result = conn.execute(
                    text("""
                        UPDATE tasks
                        SET assigned_to_line_user_id = :line_user_id,
                            assigned_to_display_name = :display_name,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :task_id AND group_id IS NOT NULL
                        RETURNING id
                    """),
                    {
                        "task_id": task_id,
                        "line_user_id": line_user_id,
                        "display_name": display_name or "担当者"
                    }
                )

                if result.rowcount > 0:
                    print(f"✅ タスク割り当て: task_id={task_id}, assigned_to={line_user_id}")
                    return True
                else:
                    print(f"⚠️ タスク割り当て失敗: task_id={task_id}")
                    return False

    def delete_group(self, group_id: str) -> None:
        """
        グループを削除（論理削除）

        Args:
            group_id: グループID
        """
        with self.engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("""
                        UPDATE groups
                        SET is_deleted = true,
                            status = 'inactive',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :group_id
                    """),
                    {"group_id": group_id}
                )

                print(f"✅ グループ削除: group_id={group_id}")
