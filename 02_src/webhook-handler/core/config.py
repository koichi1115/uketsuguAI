"""
設定管理モジュール
Secret Managerからのシークレット取得とLINE API設定を管理
"""
import os
from google.cloud import secretmanager
from linebot.v3.messaging import Configuration

# 環境変数からGCP設定を取得
PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
REGION = os.environ.get('GCP_REGION', 'asia-northeast1')

# グローバル変数（遅延初期化）
_configuration = None


def get_secret(secret_id: str) -> str:
    """Secret Managerからシークレットを取得"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def get_configuration():
    """LINE API Configurationを取得（遅延初期化）"""
    global _configuration
    if _configuration is None:
        channel_access_token = get_secret('LINE_CHANNEL_ACCESS_TOKEN')
        _configuration = Configuration(access_token=channel_access_token)
    return _configuration
