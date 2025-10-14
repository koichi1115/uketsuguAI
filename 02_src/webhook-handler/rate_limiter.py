"""
レート制限機能
Phase 1: 悪用対策 - 100ポスト/日/ユーザー制限
"""
from datetime import date
from typing import Optional, Tuple
import sqlalchemy
from sqlalchemy import text


class RateLimiter:
    """ユーザーごとのメッセージポスト制限を管理"""

    # 制限値: 100ポスト/日
    DAILY_LIMIT = 100

    # 制限超過時のエラーメッセージ
    LIMIT_EXCEEDED_MESSAGE = "制限を超えました。24時間待ってから再開してください"

    def __init__(self, engine: sqlalchemy.engine.Engine):
        """
        Args:
            engine: SQLAlchemy Engineインスタンス
        """
        self.engine = engine

    def check_rate_limit(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        ユーザーのレート制限をチェック

        Args:
            user_id: ユーザーのUUID

        Returns:
            (制限内かどうか, エラーメッセージ)
            - (True, None): 制限内
            - (False, エラーメッセージ): 制限超過
        """
        today = date.today()

        with self.engine.connect() as conn:
            # トランザクション開始
            with conn.begin():
                # 今日のメッセージカウントを取得または作成
                result = conn.execute(
                    text("""
                        INSERT INTO rate_limits (user_id, limit_date, message_count)
                        VALUES (:user_id, :limit_date, 1)
                        ON CONFLICT (user_id, limit_date)
                        DO UPDATE SET
                            message_count = rate_limits.message_count + 1,
                            updated_at = CURRENT_TIMESTAMP
                        RETURNING message_count
                    """),
                    {"user_id": user_id, "limit_date": today}
                )

                row = result.fetchone()
                current_count = row[0] if row else 0

                # 制限チェック
                if current_count > self.DAILY_LIMIT:
                    return False, self.LIMIT_EXCEEDED_MESSAGE

                return True, None

    def get_current_count(self, user_id: str) -> int:
        """
        ユーザーの今日のメッセージカウントを取得

        Args:
            user_id: ユーザーのUUID

        Returns:
            今日のメッセージ数
        """
        today = date.today()

        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT message_count
                    FROM rate_limits
                    WHERE user_id = :user_id AND limit_date = :limit_date
                """),
                {"user_id": user_id, "limit_date": today}
            )

            row = result.fetchone()
            return row[0] if row else 0

    def reset_count(self, user_id: str) -> None:
        """
        ユーザーの今日のメッセージカウントをリセット（テスト用）

        Args:
            user_id: ユーザーのUUID
        """
        today = date.today()

        with self.engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("""
                        DELETE FROM rate_limits
                        WHERE user_id = :user_id AND limit_date = :limit_date
                    """),
                    {"user_id": user_id, "limit_date": today}
                )

    @staticmethod
    def cleanup_old_records(engine: sqlalchemy.engine.Engine, days: int = 7) -> int:
        """
        古いレート制限レコードを削除（定期実行用）

        Args:
            engine: SQLAlchemy Engineインスタンス
            days: 保持期間（日数）デフォルト7日

        Returns:
            削除されたレコード数
        """
        with engine.connect() as conn:
            with conn.begin():
                result = conn.execute(
                    text("""
                        DELETE FROM rate_limits
                        WHERE limit_date < CURRENT_DATE - INTERVAL ':days days'
                    """),
                    {"days": days}
                )
                return result.rowcount


def is_rate_limited(user_id: str, engine: sqlalchemy.engine.Engine) -> Tuple[bool, Optional[str]]:
    """
    レート制限チェックのヘルパー関数

    Args:
        user_id: ユーザーのUUID
        engine: SQLAlchemy Engineインスタンス

    Returns:
        (制限されているか, エラーメッセージ)
        - (False, None): 制限内
        - (True, エラーメッセージ): 制限超過
    """
    limiter = RateLimiter(engine)
    is_allowed, error_msg = limiter.check_rate_limit(user_id)

    # 戻り値を反転（is_rate_limitedなので、制限されている=True）
    return not is_allowed, error_msg
