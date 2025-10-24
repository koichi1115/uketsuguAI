"""
サブスクリプション管理サービス

このモジュールは、ユーザーのサブスクリプション管理機能を提供します。
- サブスクリプションステータスの取得
- Stripeとの連携による解約処理
- プラン情報の取得
"""

import os
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import stripe
import sqlalchemy
from google.cloud import secretmanager


# Stripe APIキーの遅延初期化
_stripe_initialized = False


def get_secret(secret_id: str, project_id: str) -> str:
    """Secret Managerからシークレットを取得"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def initialize_stripe():
    """Stripe APIを初期化"""
    global _stripe_initialized
    if not _stripe_initialized:
        project_id = os.environ.get('GCP_PROJECT_ID')
        stripe_api_key = get_secret('STRIPE_API_KEY', project_id)
        stripe.api_key = stripe_api_key
        _stripe_initialized = True


def get_user_subscription(engine, user_id: str) -> Optional[Dict[str, Any]]:
    """
    ユーザーのサブスクリプション情報を取得

    Args:
        engine: SQLAlchemy engine
        user_id: ユーザーID (UUID)

    Returns:
        サブスクリプション情報の辞書、またはNone
    """
    with engine.connect() as conn:
        result = conn.execute(
            sqlalchemy.text(
                """
                SELECT
                    s.id,
                    s.plan_type,
                    s.status,
                    s.start_date,
                    s.end_date,
                    s.stripe_customer_id,
                    s.stripe_subscription_id,
                    s.created_at,
                    s.updated_at
                FROM subscriptions s
                WHERE s.user_id = :user_id
                    AND s.status IN ('active', 'trialing')
                ORDER BY s.created_at DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id}
        ).fetchone()

        if not result:
            return None

        return {
            'id': result[0],
            'plan_type': result[1],
            'status': result[2],
            'start_date': result[3],
            'end_date': result[4],
            'stripe_customer_id': result[5],
            'stripe_subscription_id': result[6],
            'created_at': result[7],
            'updated_at': result[8]
        }


def get_plan_display_name(plan_type: str) -> str:
    """
    プランタイプの表示名を取得

    Args:
        plan_type: プランタイプ (beta, standard, premium)

    Returns:
        プランの表示名
    """
    plan_names = {
        'beta': 'ベータプラン',
        'standard': 'スタンダードプラン',
        'premium': 'プレミアムプラン'
    }
    return plan_names.get(plan_type, plan_type)


def get_status_display_name(status: str) -> str:
    """
    ステータスの表示名を取得

    Args:
        status: ステータス (active, canceled, expired, trialing)

    Returns:
        ステータスの表示名
    """
    status_names = {
        'active': '有効',
        'canceled': '解約済み',
        'expired': '期限切れ',
        'trialing': 'トライアル中'
    }
    return status_names.get(status, status)


def cancel_subscription(engine, user_id: str, stripe_subscription_id: str) -> bool:
    """
    サブスクリプションを解約

    Args:
        engine: SQLAlchemy engine
        user_id: ユーザーID (UUID)
        stripe_subscription_id: StripeサブスクリプションID

    Returns:
        成功した場合True、失敗した場合False
    """
    try:
        # Stripe APIを初期化
        initialize_stripe()

        # Stripe側で解約処理（即座に解約）
        # at_period_end=False: 即座に解約
        # at_period_end=True: 期間終了時に解約（推奨）
        stripe.Subscription.delete(stripe_subscription_id)

        # データベースを更新
        with engine.connect() as conn:
            conn.execute(
                sqlalchemy.text(
                    """
                    UPDATE subscriptions
                    SET status = 'canceled',
                        updated_at = :updated_at
                    WHERE user_id = :user_id
                        AND stripe_subscription_id = :stripe_subscription_id
                    """
                ),
                {
                    "user_id": user_id,
                    "stripe_subscription_id": stripe_subscription_id,
                    "updated_at": datetime.now(timezone.utc)
                }
            )
            conn.commit()

        return True

    except stripe.error.StripeError as e:
        print(f"❌ Stripe error during cancellation: {e}")
        return False
    except Exception as e:
        print(f"❌ Error during cancellation: {e}")
        return False


def get_subscription_from_stripe(stripe_subscription_id: str) -> Optional[Dict[str, Any]]:
    """
    StripeからサブスクリプションIDでサブスクリプション情報を取得

    Args:
        stripe_subscription_id: StripeサブスクリプションID

    Returns:
        Stripeのサブスクリプション情報、またはNone
    """
    try:
        initialize_stripe()
        subscription = stripe.Subscription.retrieve(stripe_subscription_id)
        return subscription
    except stripe.error.StripeError as e:
        print(f"❌ Stripe error: {e}")
        return None


def update_subscription_from_stripe(engine, user_id: str, stripe_data: Dict[str, Any]) -> bool:
    """
    Stripeのデータでデータベースのサブスクリプション情報を更新

    Args:
        engine: SQLAlchemy engine
        user_id: ユーザーID (UUID)
        stripe_data: Stripeから取得したサブスクリプションデータ

    Returns:
        成功した場合True
    """
    try:
        # Stripeのステータスをマッピング
        status_mapping = {
            'active': 'active',
            'trialing': 'trialing',
            'canceled': 'canceled',
            'past_due': 'active',  # 支払い遅延も一旦activeとして扱う
            'unpaid': 'canceled',
            'incomplete': 'trialing',
            'incomplete_expired': 'expired'
        }

        status = status_mapping.get(stripe_data.get('status'), 'active')

        with engine.connect() as conn:
            conn.execute(
                sqlalchemy.text(
                    """
                    UPDATE subscriptions
                    SET status = :status,
                        updated_at = :updated_at
                    WHERE user_id = :user_id
                        AND stripe_subscription_id = :stripe_subscription_id
                    """
                ),
                {
                    "user_id": user_id,
                    "stripe_subscription_id": stripe_data.get('id'),
                    "status": status,
                    "updated_at": datetime.now(timezone.utc)
                }
            )
            conn.commit()

        return True

    except Exception as e:
        print(f"❌ Error updating subscription: {e}")
        return False
