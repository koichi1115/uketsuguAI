"""
プラン管理モジュール
Phase 3: 段階的価格設定（無料/ベーシック/プレミアム）
"""
from typing import Optional, Dict, Tuple
from datetime import datetime, timezone
import sqlalchemy
from sqlalchemy import text


# プラン定義
PLAN_DEFINITIONS = {
    'free': {
        'name': '無料プラン',
        'price': 0,
        'ai_chat_limit': 0,  # チャット不可
        'task_generation_limit': 1,  # タスク生成1回のみ
        'group_enabled': False
    },
    'basic': {
        'name': 'ベーシックプラン',
        'price': 300,
        'ai_chat_limit': 10,  # 月10回まで
        'task_generation_limit': 1,
        'group_enabled': False
    },
    'premium': {
        'name': 'プレミアムプラン',
        'price': 500,
        'ai_chat_limit': -1,  # 無制限
        'task_generation_limit': 1,
        'group_enabled': True
    }
}


class PlanManager:
    """プラン機能の管理"""

    def __init__(self, engine: sqlalchemy.engine.Engine):
        """
        Args:
            engine: SQLAlchemy Engineインスタンス
        """
        self.engine = engine

    def get_user_plan(self, user_id: str) -> Optional[Dict]:
        """
        ユーザーのプラン情報を取得

        Args:
            user_id: ユーザーID

        Returns:
            プラン情報、存在しない場合はNone
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        plan_type,
                        status,
                        ai_chat_count,
                        ai_chat_limit,
                        task_generation_count,
                        task_generation_limit,
                        group_enabled,
                        last_reset_at
                    FROM subscriptions
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"user_id": user_id}
            ).fetchone()

            if not result:
                return None

            plan_type, status, ai_chat_count, ai_chat_limit, task_gen_count, task_gen_limit, group_enabled, last_reset_at = result

            return {
                "plan_type": plan_type,
                "status": status,
                "ai_chat_count": ai_chat_count,
                "ai_chat_limit": ai_chat_limit,
                "task_generation_count": task_gen_count,
                "task_generation_limit": task_gen_limit,
                "group_enabled": group_enabled,
                "last_reset_at": last_reset_at
            }

    def check_and_reset_monthly_counters(self, user_id: str) -> None:
        """
        月初カウンターリセットが必要かチェックし、必要なら実行

        Args:
            user_id: ユーザーID
        """
        with self.engine.connect() as conn:
            with conn.begin():
                # 最終リセット日時を取得
                result = conn.execute(
                    text("""
                        SELECT last_reset_at
                        FROM subscriptions
                        WHERE user_id = :user_id
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"user_id": user_id}
                ).fetchone()

                if not result or not result[0]:
                    return

                last_reset_at = result[0]
                now = datetime.now(timezone.utc)

                # 月が変わっていたらリセット
                if last_reset_at.month != now.month or last_reset_at.year != now.year:
                    conn.execute(
                        text("""
                            UPDATE subscriptions
                            SET
                                ai_chat_count = 0,
                                task_generation_count = 0,
                                last_reset_at = :now
                            WHERE user_id = :user_id
                        """),
                        {"user_id": user_id, "now": now}
                    )
                    print(f"✅ カウンターリセット: user_id={user_id}, {last_reset_at.strftime('%Y-%m')} → {now.strftime('%Y-%m')}")

    def can_use_ai_chat(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        ユーザーがAIチャットを利用できるかチェック

        Args:
            user_id: ユーザーID

        Returns:
            (利用可能か, エラーメッセージ)
        """
        # 月初リセットチェック
        self.check_and_reset_monthly_counters(user_id)

        plan = self.get_user_plan(user_id)

        if not plan:
            return False, "❌ プラン情報が見つかりません。"

        if plan["status"] != "active":
            return False, "❌ 有効なプランがありません。"

        # 無制限プラン（-1）の場合
        if plan["ai_chat_limit"] == -1:
            return True, None

        # 利用不可プラン（0）の場合
        if plan["ai_chat_limit"] == 0:
            plan_def = PLAN_DEFINITIONS.get(plan["plan_type"], {})
            plan_name = plan_def.get("name", "現在のプラン")

            if plan["plan_type"] == "free":
                return False, (
                    f"❌ {plan_name}ではAIチャット機能はご利用いただけません。\n\n"
                    "✨ ベーシックプラン（月額300円）にアップグレードすると、\n"
                    "月10回までAIチャットが利用できます。\n\n"
                    "「アップグレード」と入力してプランをご確認ください。"
                )
            else:
                return False, f"❌ {plan_name}ではAIチャット機能はご利用いただけません。"

        # 利用回数チェック
        if plan["ai_chat_count"] >= plan["ai_chat_limit"]:
            plan_def = PLAN_DEFINITIONS.get(plan["plan_type"], {})
            plan_name = plan_def.get("name", "現在のプラン")

            if plan["plan_type"] == "basic":
                return False, (
                    f"❌ 今月のAIチャット利用回数が上限に達しました。\n"
                    f"（{plan['ai_chat_count']}/{plan['ai_chat_limit']}回）\n\n"
                    "✨ プレミアムプラン（月額500円）にアップグレードすると、\n"
                    "チャット無制限＋グループLINE機能が使えます。\n\n"
                    "「アップグレード」と入力してプランをご確認ください。"
                )
            else:
                return False, (
                    f"❌ 今月のAIチャット利用回数が上限に達しました。\n"
                    f"（{plan['ai_chat_count']}/{plan['ai_chat_limit']}回）"
                )

        return True, None

    def increment_ai_chat_count(self, user_id: str) -> bool:
        """
        AIチャット利用回数をインクリメント

        Args:
            user_id: ユーザーID

        Returns:
            成功したらTrue
        """
        with self.engine.connect() as conn:
            with conn.begin():
                result = conn.execute(
                    text("""
                        UPDATE subscriptions
                        SET
                            ai_chat_count = ai_chat_count + 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = :user_id
                        RETURNING ai_chat_count, ai_chat_limit
                    """),
                    {"user_id": user_id}
                )

                row = result.fetchone()
                if row:
                    new_count, limit = row
                    limit_str = "無制限" if limit == -1 else f"{limit}回"
                    print(f"✅ AIチャットカウント更新: user_id={user_id}, {new_count}/{limit_str}")
                    return True
                else:
                    print(f"⚠️ AIチャットカウント更新失敗: user_id={user_id}")
                    return False

    def can_generate_tasks(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        ユーザーがタスク生成を実行できるかチェック

        Args:
            user_id: ユーザーID

        Returns:
            (実行可能か, エラーメッセージ)
        """
        # 月初リセットチェック
        self.check_and_reset_monthly_counters(user_id)

        plan = self.get_user_plan(user_id)

        if not plan:
            return False, "❌ プラン情報が見つかりません。"

        if plan["status"] != "active":
            return False, "❌ 有効なプランがありません。"

        # 利用回数チェック
        if plan["task_generation_count"] >= plan["task_generation_limit"]:
            return False, (
                f"❌ 今月のタスク生成実行回数が上限に達しました。\n"
                f"（{plan['task_generation_count']}/{plan['task_generation_limit']}回）\n\n"
                "💡 来月1日に自動的にリセットされます。"
            )

        return True, None

    def increment_task_generation_count(self, user_id: str) -> bool:
        """
        タスク生成実行回数をインクリメント

        Args:
            user_id: ユーザーID

        Returns:
            成功したらTrue
        """
        with self.engine.connect() as conn:
            with conn.begin():
                result = conn.execute(
                    text("""
                        UPDATE subscriptions
                        SET
                            task_generation_count = task_generation_count + 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = :user_id
                        RETURNING task_generation_count, task_generation_limit
                    """),
                    {"user_id": user_id}
                )

                row = result.fetchone()
                if row:
                    new_count, limit = row
                    print(f"✅ タスク生成カウント更新: user_id={user_id}, {new_count}/{limit}回")
                    return True
                else:
                    print(f"⚠️ タスク生成カウント更新失敗: user_id={user_id}")
                    return False

    def can_use_group_feature(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        ユーザーがグループLINE機能を利用できるかチェック

        Args:
            user_id: ユーザーID

        Returns:
            (利用可能か, エラーメッセージ)
        """
        plan = self.get_user_plan(user_id)

        if not plan:
            return False, "❌ プラン情報が見つかりません。"

        if plan["status"] != "active":
            return False, "❌ 有効なプランがありません。"

        if not plan["group_enabled"]:
            plan_def = PLAN_DEFINITIONS.get(plan["plan_type"], {})
            plan_name = plan_def.get("name", "現在のプラン")

            return False, (
                f"❌ {plan_name}ではグループLINE機能はご利用いただけません。\n\n"
                "✨ プレミアムプラン（月額500円）にアップグレードすると、\n"
                "グループLINE機能＋チャット無制限が使えます。\n\n"
                "「アップグレード」と入力してプランをご確認ください。"
            )

        return True, None

    def get_plan_info_message(self, user_id: str) -> str:
        """
        ユーザーのプラン情報メッセージを生成

        Args:
            user_id: ユーザーID

        Returns:
            プラン情報メッセージ
        """
        plan = self.get_user_plan(user_id)

        if not plan:
            return "❌ プラン情報が見つかりません。"

        plan_def = PLAN_DEFINITIONS.get(plan["plan_type"], {})
        plan_name = plan_def.get("name", plan["plan_type"])
        price = plan_def.get("price", 0)

        # AIチャット回数の表示
        if plan["ai_chat_limit"] == -1:
            chat_usage = "無制限"
        elif plan["ai_chat_limit"] == 0:
            chat_usage = "利用不可"
        else:
            remaining = plan["ai_chat_limit"] - plan["ai_chat_count"]
            chat_usage = f"あと{remaining}回 ({plan['ai_chat_count']}/{plan['ai_chat_limit']}回使用)"

        # タスク生成回数の表示
        task_remaining = plan["task_generation_limit"] - plan["task_generation_count"]
        task_usage = f"あと{task_remaining}回 ({plan['task_generation_count']}/{plan['task_generation_limit']}回使用)"

        # グループLINE機能の表示
        group_status = "✅ 利用可能" if plan["group_enabled"] else "❌ 利用不可"

        message = f"""📊 現在のプラン情報

【プラン】
{plan_name}（月額{price}円）

【今月の利用状況】
🤖 AIチャット: {chat_usage}
📋 タスク生成: {task_usage}
👥 グループLINE: {group_status}

【リセット日】
{plan['last_reset_at'].strftime('%Y年%m月01日')}（毎月1日）"""

        # アップグレード案内
        if plan["plan_type"] == "free":
            message += "\n\n✨ ベーシックプラン（月額300円）にアップグレードすると、月10回までAIチャットが利用できます。"
        elif plan["plan_type"] == "basic":
            message += "\n\n✨ プレミアムプラン（月額500円）にアップグレードすると、チャット無制限＋グループLINE機能が使えます。"

        return message
