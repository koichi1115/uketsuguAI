"""
Stripe Webhook ハンドラー

このモジュールは、Stripeからのwebhookイベントを処理します。
- 署名検証
- イベント処理（subscription.created, subscription.updated, subscription.deleted等）
- データベース更新
"""

import os
import stripe
import sqlalchemy
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from google.cloud import secretmanager


def get_secret(secret_id: str, project_id: str) -> str:
    """Secret Managerからシークレットを取得"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def verify_stripe_signature(payload: str, sig_header: str, webhook_secret: str) -> Optional[Dict[str, Any]]:
    """
    Stripe webhook署名を検証

    Args:
        payload: リクエストボディ（生データ）
        sig_header: Stripe-Signatureヘッダー
        webhook_secret: Stripe Webhook Secret

    Returns:
        検証成功時はイベントオブジェクト、失敗時はNone
    """
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        return event
    except ValueError as e:
        print(f"❌ Invalid payload: {e}")
        return None
    except stripe.error.SignatureVerificationError as e:
        print(f"❌ Invalid signature: {e}")
        return None


def handle_subscription_created(engine, event_data: Dict[str, Any]) -> bool:
    """
    customer.subscription.created イベントを処理

    Args:
        engine: SQLAlchemy engine
        event_data: Stripeイベントデータ

    Returns:
        処理成功時True
    """
    try:
        subscription = event_data['object']
        customer_id = subscription['customer']
        subscription_id = subscription['id']
        status = subscription['status']

        # プランIDからplan_typeを判定
        # 例: price_beta_monthly -> beta
        plan_id = subscription['items']['data'][0]['plan']['id']
        plan_type = 'standard'  # デフォルト
        if 'beta' in plan_id:
            plan_type = 'beta'
        elif 'premium' in plan_id:
            plan_type = 'premium'

        # 開始日と終了日
        start_date = datetime.fromtimestamp(subscription['current_period_start'], tz=timezone.utc)
        end_date = datetime.fromtimestamp(subscription['current_period_end'], tz=timezone.utc)

        # ユーザーIDをstripe_customer_idから取得
        with engine.connect() as conn:
            # まずユーザーを探す（仮にusersテーブルにstripe_customer_idがあると想定）
            # 実際の実装ではユーザーテーブルの構造に合わせて調整が必要
            user_result = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT id FROM users WHERE stripe_customer_id = :customer_id LIMIT 1
                    """
                ),
                {"customer_id": customer_id}
            ).fetchone()

            if not user_result:
                print(f"⚠️ User not found for customer_id: {customer_id}")
                # ユーザーが見つからない場合は、メタデータやメールから検索する必要がある
                # ここでは一旦スキップ
                return False

            user_id = user_result[0]

            # サブスクリプションを作成
            conn.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO subscriptions
                        (user_id, plan_type, status, start_date, end_date,
                         stripe_customer_id, stripe_subscription_id)
                    VALUES
                        (:user_id, :plan_type, :status, :start_date, :end_date,
                         :stripe_customer_id, :stripe_subscription_id)
                    """
                ),
                {
                    "user_id": user_id,
                    "plan_type": plan_type,
                    "status": status,
                    "start_date": start_date,
                    "end_date": end_date,
                    "stripe_customer_id": customer_id,
                    "stripe_subscription_id": subscription_id
                }
            )
            conn.commit()

        print(f"✅ Subscription created: {subscription_id}")
        return True

    except Exception as e:
        print(f"❌ Error handling subscription.created: {e}")
        return False


def handle_subscription_updated(engine, event_data: Dict[str, Any]) -> bool:
    """
    customer.subscription.updated イベントを処理

    Args:
        engine: SQLAlchemy engine
        event_data: Stripeイベントデータ

    Returns:
        処理成功時True
    """
    try:
        subscription = event_data['object']
        subscription_id = subscription['id']
        status = subscription['status']
        end_date = datetime.fromtimestamp(subscription['current_period_end'], tz=timezone.utc)

        # データベースを更新
        with engine.connect() as conn:
            conn.execute(
                sqlalchemy.text(
                    """
                    UPDATE subscriptions
                    SET status = :status,
                        end_date = :end_date,
                        updated_at = :updated_at
                    WHERE stripe_subscription_id = :subscription_id
                    """
                ),
                {
                    "status": status,
                    "end_date": end_date,
                    "subscription_id": subscription_id,
                    "updated_at": datetime.now(timezone.utc)
                }
            )
            conn.commit()

        print(f"✅ Subscription updated: {subscription_id}")
        return True

    except Exception as e:
        print(f"❌ Error handling subscription.updated: {e}")
        return False


def handle_subscription_deleted(engine, event_data: Dict[str, Any]) -> bool:
    """
    customer.subscription.deleted イベントを処理

    Args:
        engine: SQLAlchemy engine
        event_data: Stripeイベントデータ

    Returns:
        処理成功時True
    """
    try:
        subscription = event_data['object']
        subscription_id = subscription['id']

        # データベースを更新（ステータスをcanceledに）
        with engine.connect() as conn:
            conn.execute(
                sqlalchemy.text(
                    """
                    UPDATE subscriptions
                    SET status = 'canceled',
                        updated_at = :updated_at
                    WHERE stripe_subscription_id = :subscription_id
                    """
                ),
                {
                    "subscription_id": subscription_id,
                    "updated_at": datetime.now(timezone.utc)
                }
            )
            conn.commit()

        print(f"✅ Subscription deleted: {subscription_id}")
        return True

    except Exception as e:
        print(f"❌ Error handling subscription.deleted: {e}")
        return False


def handle_invoice_payment_succeeded(engine, event_data: Dict[str, Any]) -> bool:
    """
    invoice.payment_succeeded イベントを処理

    Args:
        engine: SQLAlchemy engine
        event_data: Stripeイベントデータ

    Returns:
        処理成功時True
    """
    try:
        invoice = event_data['object']
        subscription_id = invoice.get('subscription')

        if not subscription_id:
            # サブスクリプションに関連しない支払い
            return True

        # サブスクリプションのステータスをactiveに更新
        with engine.connect() as conn:
            conn.execute(
                sqlalchemy.text(
                    """
                    UPDATE subscriptions
                    SET status = 'active',
                        updated_at = :updated_at
                    WHERE stripe_subscription_id = :subscription_id
                    """
                ),
                {
                    "subscription_id": subscription_id,
                    "updated_at": datetime.now(timezone.utc)
                }
            )
            conn.commit()

        print(f"✅ Payment succeeded for subscription: {subscription_id}")
        return True

    except Exception as e:
        print(f"❌ Error handling invoice.payment_succeeded: {e}")
        return False


def handle_invoice_payment_failed(engine, event_data: Dict[str, Any]) -> bool:
    """
    invoice.payment_failed イベントを処理

    Args:
        engine: SQLAlchemy engine
        event_data: Stripeイベントデータ

    Returns:
        処理成功時True
    """
    try:
        invoice = event_data['object']
        subscription_id = invoice.get('subscription')
        customer_id = invoice.get('customer')

        if not subscription_id:
            return True

        print(f"⚠️ Payment failed for subscription: {subscription_id}")
        # 必要に応じて、ユーザーに通知を送る処理を追加

        # ステータスは一旦そのまま（Stripeが自動的に処理する）
        return True

    except Exception as e:
        print(f"❌ Error handling invoice.payment_failed: {e}")
        return False


def process_webhook_event(engine, event: Dict[str, Any]) -> bool:
    """
    Webhookイベントを処理

    Args:
        engine: SQLAlchemy engine
        event: Stripeイベントオブジェクト

    Returns:
        処理成功時True
    """
    event_type = event['type']
    event_data = event['data']

    print(f"📨 Received webhook event: {event_type}")

    # イベントタイプに応じて処理を分岐
    handlers = {
        'customer.subscription.created': handle_subscription_created,
        'customer.subscription.updated': handle_subscription_updated,
        'customer.subscription.deleted': handle_subscription_deleted,
        'invoice.payment_succeeded': handle_invoice_payment_succeeded,
        'invoice.payment_failed': handle_invoice_payment_failed,
    }

    handler = handlers.get(event_type)
    if handler:
        return handler(engine, event_data)
    else:
        print(f"ℹ️ Unhandled event type: {event_type}")
        return True  # 未処理のイベントはエラーとしない
