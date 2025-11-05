"""
認証・認可ユーティリティモジュール

ユーザーの所有権検証とアクセス制御を提供
"""

import sqlalchemy
from typing import Optional


class AuthorizationError(Exception):
    """認可エラー"""
    pass


def verify_user_ownership(conn, line_user_id: str, user_id: str) -> bool:
    """
    line_user_id と user_id の関連性を検証

    Args:
        conn: データベース接続
        line_user_id: LINE ユーザーID
        user_id: 内部ユーザーID

    Returns:
        True: 検証成功

    Raises:
        AuthorizationError: 検証失敗時
    """
    result = conn.execute(
        sqlalchemy.text(
            """
            SELECT id FROM users
            WHERE line_user_id = :line_user_id AND id = :user_id
            """
        ),
        {"line_user_id": line_user_id, "user_id": user_id}
    ).fetchone()

    if not result:
        raise AuthorizationError(
            f"User ownership verification failed: line_user_id={line_user_id}, user_id={user_id}"
        )

    return True


def get_user_id_from_line_id(conn, line_user_id: str) -> Optional[str]:
    """
    line_user_id から安全に user_id を取得

    Args:
        conn: データベース接続
        line_user_id: LINE ユーザーID

    Returns:
        user_id または None
    """
    result = conn.execute(
        sqlalchemy.text(
            """
            SELECT id FROM users
            WHERE line_user_id = :line_user_id
            """
        ),
        {"line_user_id": line_user_id}
    ).fetchone()

    return result[0] if result else None


def verify_task_ownership(conn, user_id: str, task_id: str) -> bool:
    """
    タスクの所有権を検証

    Args:
        conn: データベース接続
        user_id: ユーザーID
        task_id: タスクID

    Returns:
        True: 検証成功

    Raises:
        AuthorizationError: 検証失敗時
    """
    result = conn.execute(
        sqlalchemy.text(
            """
            SELECT id FROM tasks
            WHERE id = :task_id AND user_id = :user_id AND is_deleted = false
            """
        ),
        {"task_id": task_id, "user_id": user_id}
    ).fetchone()

    if not result:
        raise AuthorizationError(
            f"Task ownership verification failed: user_id={user_id}, task_id={task_id}"
        )

    return True


def verify_profile_ownership(conn, user_id: str, profile_id: Optional[str] = None) -> bool:
    """
    プロフィールの所有権を検証

    Args:
        conn: データベース接続
        user_id: ユーザーID
        profile_id: プロフィールID（オプション）

    Returns:
        True: 検証成功

    Raises:
        AuthorizationError: 検証失敗時
    """
    if profile_id:
        result = conn.execute(
            sqlalchemy.text(
                """
                SELECT id FROM user_profiles
                WHERE id = :profile_id AND user_id = :user_id
                """
            ),
            {"profile_id": profile_id, "user_id": user_id}
        ).fetchone()
    else:
        result = conn.execute(
            sqlalchemy.text(
                """
                SELECT id FROM user_profiles
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id}
        ).fetchone()

    if not result:
        raise AuthorizationError(
            f"Profile ownership verification failed: user_id={user_id}"
        )

    return True
