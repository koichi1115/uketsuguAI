"""
会話フロー管理モジュール

ユーザーとの会話状態を管理し、タスク生成の各ステップを
適切なタイミングで実行する
"""

from typing import Dict, Optional, List
import sqlalchemy
from datetime import datetime, timedelta
import json


class ConversationState:
    """会話状態の定義"""
    INITIAL = 'initial'
    PROFILE_COLLECTION = 'profile_collection'
    BASIC_TASKS_GENERATED = 'basic_tasks_generated'
    AWAITING_FOLLOW_UP_ANSWERS = 'awaiting_follow_up_answers'
    PERSONALIZED_TASKS_GENERATING = 'personalized_tasks_generating'
    PERSONALIZED_TASKS_GENERATED = 'personalized_tasks_generated'
    ENHANCED_TASKS_GENERATING = 'enhanced_tasks_generating'
    COMPLETED = 'completed'


class ConversationFlowManager:
    """会話フロー管理クラス"""

    def __init__(self, conn):
        self.conn = conn

    def get_current_state(self, user_id: str) -> Optional[str]:
        """
        ユーザーの現在の会話状態を取得

        Args:
            user_id: ユーザーID

        Returns:
            現在の状態名、または None
        """

        result = self.conn.execute(
            sqlalchemy.text(
                """
                SELECT state_name, state_data, expires_at
                FROM conversation_states
                WHERE user_id = :user_id
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ),
            {'user_id': user_id}
        ).fetchone()

        if not result:
            return ConversationState.INITIAL

        state_name, state_data, expires_at = result

        # 有効期限チェック
        if expires_at and datetime.now() > expires_at:
            return ConversationState.INITIAL

        return state_name

    def set_state(
        self,
        user_id: str,
        state_name: str,
        state_data: Optional[Dict] = None,
        expires_in_hours: int = 24
    ):
        """
        ユーザーの会話状態を設定

        Args:
            user_id: ユーザーID
            state_name: 状態名
            state_data: 状態に関連するデータ
            expires_in_hours: 有効期限（時間）
        """

        expires_at = datetime.now() + timedelta(hours=expires_in_hours)

        # 既存の状態を更新または新規作成
        self.conn.execute(
            sqlalchemy.text(
                """
                INSERT INTO conversation_states (user_id, state_name, state_data, expires_at)
                VALUES (:user_id, :state_name, :state_data, :expires_at)
                ON CONFLICT (user_id, state_name)
                DO UPDATE SET
                    state_data = EXCLUDED.state_data,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {
                'user_id': user_id,
                'state_name': state_name,
                'state_data': json.dumps(state_data) if state_data else None,
                'expires_at': expires_at
            }
        )

        self.conn.commit()

    def get_state_data(self, user_id: str, state_name: str) -> Optional[Dict]:
        """
        特定の状態のデータを取得

        Args:
            user_id: ユーザーID
            state_name: 状態名

        Returns:
            状態データ、または None
        """

        result = self.conn.execute(
            sqlalchemy.text(
                """
                SELECT state_data FROM conversation_states
                WHERE user_id = :user_id AND state_name = :state_name
                """
            ),
            {'user_id': user_id, 'state_name': state_name}
        ).fetchone()

        if not result or not result[0]:
            return None

        return json.loads(result[0]) if isinstance(result[0], str) else result[0]

    def clear_state(self, user_id: str, state_name: Optional[str] = None):
        """
        ユーザーの会話状態をクリア

        Args:
            user_id: ユーザーID
            state_name: 特定の状態名（Noneの場合はすべてクリア）
        """

        if state_name:
            self.conn.execute(
                sqlalchemy.text(
                    """
                    DELETE FROM conversation_states
                    WHERE user_id = :user_id AND state_name = :state_name
                    """
                ),
                {'user_id': user_id, 'state_name': state_name}
            )
        else:
            self.conn.execute(
                sqlalchemy.text(
                    """
                    DELETE FROM conversation_states
                    WHERE user_id = :user_id
                    """
                ),
                {'user_id': user_id}
            )

        self.conn.commit()

    def get_task_generation_step_status(self, user_id: str, step_name: str) -> Optional[str]:
        """
        タスク生成ステップの状態を取得

        Args:
            user_id: ユーザーID
            step_name: ステップ名（basic, personalized, enhanced）

        Returns:
            ステップの状態（pending, in_progress, completed, failed）
        """

        result = self.conn.execute(
            sqlalchemy.text(
                """
                SELECT status FROM task_generation_steps
                WHERE user_id = :user_id AND step_name = :step_name
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {'user_id': user_id, 'step_name': step_name}
        ).fetchone()

        return result[0] if result else None

    def set_task_generation_step_status(
        self,
        user_id: str,
        step_name: str,
        status: str,
        metadata: Optional[Dict] = None,
        error_message: Optional[str] = None
    ):
        """
        タスク生成ステップの状態を設定

        Args:
            user_id: ユーザーID
            step_name: ステップ名
            status: 状態
            metadata: メタデータ
            error_message: エラーメッセージ
        """

        # 既存のレコードを探す
        existing = self.conn.execute(
            sqlalchemy.text(
                """
                SELECT id FROM task_generation_steps
                WHERE user_id = :user_id AND step_name = :step_name
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {'user_id': user_id, 'step_name': step_name}
        ).fetchone()

        if existing:
            # 更新
            update_data = {'status': status}
            if status == 'in_progress':
                update_data['started_at'] = datetime.now()
            elif status in ['completed', 'failed']:
                update_data['completed_at'] = datetime.now()

            set_clauses = [f"{key} = :{key}" for key in update_data.keys()]
            if metadata:
                set_clauses.append("metadata = :metadata")
                update_data['metadata'] = json.dumps(metadata)
            if error_message:
                set_clauses.append("error_message = :error_message")
                update_data['error_message'] = error_message

            update_data['id'] = existing[0]

            self.conn.execute(
                sqlalchemy.text(f"""
                    UPDATE task_generation_steps
                    SET {', '.join(set_clauses)}
                    WHERE id = :id
                """),
                update_data
            )
        else:
            # 新規作成
            insert_data = {
                'user_id': user_id,
                'step_name': step_name,
                'status': status,
                'metadata': json.dumps(metadata) if metadata else None,
                'error_message': error_message
            }

            if status == 'in_progress':
                insert_data['started_at'] = datetime.now()
            elif status in ['completed', 'failed']:
                insert_data['completed_at'] = datetime.now()

            self.conn.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO task_generation_steps
                    (user_id, step_name, status, started_at, completed_at, metadata, error_message)
                    VALUES
                    (:user_id, :step_name, :status, :started_at, :completed_at, :metadata, :error_message)
                    """
                ),
                {
                    'user_id': insert_data['user_id'],
                    'step_name': insert_data['step_name'],
                    'status': insert_data['status'],
                    'started_at': insert_data.get('started_at'),
                    'completed_at': insert_data.get('completed_at'),
                    'metadata': insert_data.get('metadata'),
                    'error_message': insert_data.get('error_message')
                }
            )

        self.conn.commit()

    def should_start_personalization(self, user_id: str) -> bool:
        """
        個別タスク生成を開始すべきか判定

        Args:
            user_id: ユーザーID

        Returns:
            True: 開始すべき
        """

        # 基本タスクが完了しているか
        basic_status = self.get_task_generation_step_status(user_id, 'basic')
        if basic_status != 'completed':
            return False

        # すべての追加質問に回答済みか
        from question_generator import check_all_questions_answered
        if not check_all_questions_answered(user_id, self.conn):
            return False

        # 個別タスクがまだ生成されていないか
        personalized_status = self.get_task_generation_step_status(user_id, 'personalized')
        if personalized_status in ['completed', 'in_progress']:
            return False

        return True

    def should_start_enhancement(self, user_id: str) -> bool:
        """
        Tips収集・拡張を開始すべきか判定

        Args:
            user_id: ユーザーID

        Returns:
            True: 開始すべき
        """

        # 個別タスクが完了しているか
        personalized_status = self.get_task_generation_step_status(user_id, 'personalized')
        if personalized_status != 'completed':
            return False

        # Tips収集がまだ実行されていないか
        enhanced_status = self.get_task_generation_step_status(user_id, 'enhanced')
        if enhanced_status in ['completed', 'in_progress']:
            return False

        return True
