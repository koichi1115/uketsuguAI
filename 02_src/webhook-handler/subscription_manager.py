"""
Stripe連携とサブスクリプション管理
Phase 1: 課金システム実装
"""
import os
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import stripe
import sqlalchemy
from sqlalchemy import text


class SubscriptionManager:
    """Stripeサブスクリプション管理"""

    # プランタイプ
    PLAN_FREE = "free"
    PLAN_BETA = "beta"
    PLAN_STANDARD = "standard"

    # ステータス
    STATUS_ACTIVE = "active"
    STATUS_CANCELED = "canceled"
    STATUS_EXPIRED = "expired"

    # β版料金
    BETA_PRICE_JPY = 500

    def __init__(self, engine: sqlalchemy.engine.Engine, stripe_api_key: str):
        """
        Args:
            engine: SQLAlchemy Engineインスタンス
            stripe_api_key: Stripe APIキー
        """
        self.engine = engine
        stripe.api_key = stripe_api_key

    def get_user_subscription(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        ユーザーのサブスクリプション情報を取得

        Args:
            user_id: ユーザーのUUID

        Returns:
            サブスクリプション情報の辞書、またはNone
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, plan_type, status, start_date, end_date,
                           stripe_customer_id, stripe_subscription_id
                    FROM subscriptions
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"user_id": user_id}
            )

            row = result.fetchone()
            if not row:
                return None

            return {
                "id": str(row[0]),
                "plan_type": row[1],
                "status": row[2],
                "start_date": row[3],
                "end_date": row[4],
                "stripe_customer_id": row[5],
                "stripe_subscription_id": row[6]
            }

    def is_premium_user(self, user_id: str) -> bool:
        """
        ユーザーが有料プランかどうかを判定

        Args:
            user_id: ユーザーのUUID

        Returns:
            有料プランならTrue、無料プランまたはサブスクなしならFalse
        """
        subscription = self.get_user_subscription(user_id)

        if not subscription:
            return False

        # アクティブなベータ版または標準プランなら有料ユーザー
        is_active = subscription["status"] == self.STATUS_ACTIVE
        is_paid_plan = subscription["plan_type"] in [self.PLAN_BETA, self.PLAN_STANDARD]

        return is_active and is_paid_plan

    def create_checkout_session(
        self,
        user_id: str,
        line_user_id: str,
        success_url: str,
        cancel_url: str
    ) -> str:
        """
        Stripe Checkoutセッションを作成

        Args:
            user_id: ユーザーのUUID
            line_user_id: LINE User ID
            success_url: 成功時のリダイレクトURL
            cancel_url: キャンセル時のリダイレクトURL

        Returns:
            Checkout Session URL
        """
        # 既存のStripe顧客IDを取得
        subscription = self.get_user_subscription(user_id)
        customer_id = subscription["stripe_customer_id"] if subscription else None

        # 顧客が存在しない場合は新規作成
        if not customer_id:
            customer = stripe.Customer.create(
                metadata={
                    "user_id": user_id,
                    "line_user_id": line_user_id
                }
            )
            customer_id = customer.id

        # Checkoutセッション作成
        # 注: 実際のPriceIDは Stripe Dashboard で作成したものを使用
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "jpy",
                        "product_data": {
                            "name": "受け継ぐAI β版プラン",
                            "description": "月額サブスクリプション"
                        },
                        "unit_amount": self.BETA_PRICE_JPY,
                        "recurring": {
                            "interval": "month"
                        }
                    },
                    "quantity": 1
                }
            ],
            mode="subscription",
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={
                "user_id": user_id
            }
        )

        return session.url

    def handle_checkout_completed(self, session: Dict[str, Any]) -> None:
        """
        Checkout完了時の処理（Webhookから呼ばれる）

        Args:
            session: Stripe Checkout Sessionオブジェクト
        """
        user_id = session["metadata"]["user_id"]
        customer_id = session["customer"]
        subscription_id = session["subscription"]

        # サブスクリプション情報を取得
        subscription = stripe.Subscription.retrieve(subscription_id)

        with self.engine.connect() as conn:
            with conn.begin():
                # 既存のサブスクリプションを無効化
                conn.execute(
                    text("""
                        UPDATE subscriptions
                        SET status = :expired_status,
                            end_date = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = :user_id AND status = :active_status
                    """),
                    {
                        "user_id": user_id,
                        "active_status": self.STATUS_ACTIVE,
                        "expired_status": self.STATUS_EXPIRED
                    }
                )

                # 新しいサブスクリプションを作成
                conn.execute(
                    text("""
                        INSERT INTO subscriptions (
                            user_id, plan_type, status, start_date,
                            stripe_customer_id, stripe_subscription_id
                        ) VALUES (
                            :user_id, :plan_type, :status, :start_date,
                            :customer_id, :subscription_id
                        )
                    """),
                    {
                        "user_id": user_id,
                        "plan_type": self.PLAN_BETA,
                        "status": self.STATUS_ACTIVE,
                        "start_date": datetime.fromtimestamp(
                            subscription["current_period_start"],
                            tz=timezone.utc
                        ),
                        "customer_id": customer_id,
                        "subscription_id": subscription_id
                    }
                )

    def handle_subscription_deleted(self, subscription: Dict[str, Any]) -> None:
        """
        サブスクリプション削除時の処理（Webhookから呼ばれる）
        課金失敗や手動キャンセル時に呼ばれる

        Args:
            subscription: Stripe Subscriptionオブジェクト
        """
        subscription_id = subscription["id"]

        with self.engine.connect() as conn:
            with conn.begin():
                # サブスクリプションをキャンセル状態に更新
                conn.execute(
                    text("""
                        UPDATE subscriptions
                        SET status = :canceled_status,
                            end_date = :end_date,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE stripe_subscription_id = :subscription_id
                    """),
                    {
                        "canceled_status": self.STATUS_CANCELED,
                        "end_date": datetime.fromtimestamp(
                            subscription["ended_at"],
                            tz=timezone.utc
                        ) if subscription.get("ended_at") else datetime.now(timezone.utc),
                        "subscription_id": subscription_id
                    }
                )

    def cancel_subscription(self, user_id: str) -> bool:
        """
        ユーザーのサブスクリプションをキャンセル

        Args:
            user_id: ユーザーのUUID

        Returns:
            キャンセル成功ならTrue
        """
        subscription_info = self.get_user_subscription(user_id)

        if not subscription_info or not subscription_info.get("stripe_subscription_id"):
            return False

        try:
            # Stripeでサブスクリプションをキャンセル
            stripe.Subscription.delete(subscription_info["stripe_subscription_id"])
            return True
        except stripe.error.StripeError:
            return False
