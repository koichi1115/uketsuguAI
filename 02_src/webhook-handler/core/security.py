"""
セキュリティモジュール
LINE Webhook署名検証
"""
import hmac
import hashlib
import base64


def validate_signature(body: str, signature: str, channel_secret: str) -> bool:
    """
    LINE Webhook署名を検証

    Args:
        body: リクエストボディ
        signature: X-Line-Signature ヘッダーの値
        channel_secret: LINEチャネルシークレット

    Returns:
        署名が有効ならTrue
    """
    hash_value = hmac.new(
        channel_secret.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256
    ).digest()
    calculated_signature = base64.b64encode(hash_value).decode('utf-8')
    return calculated_signature == signature
