"""
Pay It Forward（恩送り）機能の管理モジュール
"""
import sqlalchemy
from typing import Optional, Dict, Any, List
import random


class PayItForwardManager:
    """恩送り機能を管理するクラス"""

    def __init__(self, engine):
        """
        Args:
            engine: SQLAlchemy engine
        """
        self.engine = engine

    def get_stats(self) -> Optional[Dict[str, Any]]:
        """
        恩送り統計情報を取得

        Returns:
            統計情報の辞書、またはNone
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT
                        total_payments_count,
                        total_amount,
                        available_pool_count,
                        new_users_count,
                        last_payment_at
                    FROM pay_it_forward_stats
                    LIMIT 1
                    """
                )
            ).fetchone()

            if not result:
                return None

            return {
                'total_payments_count': result[0],
                'total_amount': result[1],
                'available_pool_count': result[2],
                'new_users_count': result[3],
                'last_payment_at': result[4],
                'has_surplus': result[0] > result[3]  # 恩送り人数 > 新規ユーザー数
            }

    def get_random_message(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        ランダムに恩送りメッセージを1件取得（未閲覧のもの優先）

        Args:
            user_id: ユーザーID

        Returns:
            メッセージ情報の辞書、またはNone
        """
        with self.engine.connect() as conn:
            # 未閲覧のメッセージを優先的に取得
            result = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT p.id, p.message, p.created_at
                    FROM pay_it_forward_payments p
                    LEFT JOIN pay_it_forward_message_views v
                        ON p.id = v.payment_id AND v.user_id = :user_id
                    WHERE p.status = 'completed'
                        AND p.message IS NOT NULL
                        AND p.message != ''
                        AND v.id IS NULL
                    ORDER BY RANDOM()
                    LIMIT 1
                    """
                ),
                {"user_id": user_id}
            ).fetchone()

            # 未閲覧メッセージがない場合は、全メッセージからランダム取得
            if not result:
                result = conn.execute(
                    sqlalchemy.text(
                        """
                        SELECT id, message, created_at
                        FROM pay_it_forward_payments
                        WHERE status = 'completed'
                            AND message IS NOT NULL
                            AND message != ''
                        ORDER BY RANDOM()
                        LIMIT 1
                        """
                    )
                ).fetchone()

            if not result:
                return None

            # 閲覧履歴を記録
            conn.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO pay_it_forward_message_views (user_id, payment_id)
                    VALUES (:user_id, :payment_id)
                    ON CONFLICT (user_id, payment_id) DO NOTHING
                    """
                ),
                {"user_id": user_id, "payment_id": str(result[0])}
            )
            conn.commit()

            return {
                'id': str(result[0]),
                'message': result[1],
                'created_at': result[2]
            }

    def get_welcome_message(self, user_id: str) -> str:
        """
        初回利用時のウェルカムメッセージを生成

        Args:
            user_id: ユーザーID

        Returns:
            ウェルカムメッセージ文字列
        """
        stats = self.get_stats()
        if not stats:
            return self._get_default_welcome_message()

        if stats['has_surplus']:
            # 恩送り人数 > 新規ユーザー数の場合
            message_data = self.get_random_message(user_id)
            supporter_count = stats['total_payments_count']

            base_message = f"""こんにちは。UketsuguAIへようこそ。

あなたは、{supporter_count}人の方々の善意によって
このサービスを無料で使うことができます。"""

            if message_data and message_data['message']:
                base_message += f"""

【前のユーザーさんからのメッセージ】
「{message_data['message']}」

あなたも困っている時、
誰かに支えられています。

一緒に乗り越えていきましょう。"""
            else:
                base_message += """

あなたも困っている時、
誰かに支えられています。

一緒に乗り越えていきましょう。"""

            return base_message
        else:
            # 恩送り人数 ≦ 新規ユーザー数の場合
            return """こんにちは。UketsuguAIへようこそ。

このサービスは完全無料でご利用いただけます。

一緒に、必要な手続きを整理していきましょう。"""

    def get_high_priority_completion_message(self, user_id: str) -> str:
        """
        優先度高タスク完了時のメッセージを生成

        Args:
            user_id: ユーザーID

        Returns:
            完了メッセージ文字列
        """
        return """おめでとうございます！
優先度の高いタスクが完了しました。

もしよろしければ、このサービスが役に立ったと感じていただけたなら、
次に困っている誰かのために「恩送り」をしていただけませんか？

金額は自由です。100円でも、1000円でも構いません。
あなたの気持ちが、次の誰かを救います。

【恩送りをする】
（任意です。義務ではありません）

【後で決める】
（いつでも設定から恩送りできます）"""

    def get_final_completion_message(self) -> str:
        """
        全タスク完了時のメッセージを生成

        Returns:
            完了メッセージ文字列
        """
        return """すべてのタスクが完了しました。
本当にお疲れさまでした。

このサービスが少しでもお役に立てたなら幸いです。

もしよろしければ、次に困っている方のために
「恩送り」をご検討いただけると嬉しいです。

設定メニューからいつでも恩送りができます。

これからも、あなたを応援しています。"""

    def create_payment_link(self, user_id: str, amount: Optional[int] = None) -> str:
        """
        恩送り支払いリンクを生成（Stripe統合時に実装）

        Args:
            user_id: ユーザーID
            amount: 金額（指定なしの場合は自由入力）

        Returns:
            支払いリンクURL
        """
        # TODO: Stripe Payment Link API統合
        return "https://pay.stripe.com/pay-it-forward"

    def record_payment(
        self,
        user_id: str,
        amount: int,
        message: Optional[str] = None,
        payment_intent_id: Optional[str] = None
    ) -> bool:
        """
        恩送り支払いを記録

        Args:
            user_id: ユーザーID
            amount: 支払い金額
            message: 次のユーザーへのメッセージ（任意）
            payment_intent_id: Stripe Payment Intent ID

        Returns:
            成功した場合True
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    sqlalchemy.text(
                        """
                        INSERT INTO pay_it_forward_payments
                        (user_id, amount, message, stripe_payment_intent_id, status)
                        VALUES (:user_id, :amount, :message, :payment_intent_id, 'completed')
                        """
                    ),
                    {
                        "user_id": user_id,
                        "amount": amount,
                        "message": message,
                        "payment_intent_id": payment_intent_id
                    }
                )
                conn.commit()
                return True
        except Exception as e:
            print(f"Error recording payment: {e}")
            return False

    def _get_default_welcome_message(self) -> str:
        """
        統計情報がない場合のデフォルトメッセージ

        Returns:
            デフォルトメッセージ文字列
        """
        return """こんにちは。UketsuguAIへようこそ。

このサービスは完全無料でご利用いただけます。

一緒に、必要な手続きを整理していきましょう。"""


def get_pay_it_forward_manager(engine) -> PayItForwardManager:
    """
    PayItForwardManagerのインスタンスを取得

    Args:
        engine: SQLAlchemy engine

    Returns:
        PayItForwardManagerインスタンス
    """
    return PayItForwardManager(engine)
