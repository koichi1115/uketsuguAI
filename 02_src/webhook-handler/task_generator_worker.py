"""
非同期タスク生成ワーカー

Cloud Tasksから呼び出され、タスク生成完了後にLINE Push APIで通知する
"""

import functions_framework
from flask import Request, jsonify
import json
from task_generator import generate_basic_tasks, get_task_summary_message
from google.cloud import secretmanager
from google.cloud.sql.connector import Connector
import sqlalchemy
import os
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)


PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'uketsuguai-dev')
REGION = os.environ.get('GCP_REGION', 'asia-northeast1')

# グローバル変数（遅延初期化）
_configuration = None
_engine = None
_connector = None


def get_secret(secret_id: str) -> str:
    """Secret Managerからシークレットを取得"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def get_line_configuration():
    """LINE Messaging APIの設定を取得（遅延初期化）"""
    global _configuration

    if _configuration is None:
        channel_access_token = get_secret('LINE_CHANNEL_ACCESS_TOKEN')
        _configuration = Configuration(access_token=channel_access_token)

    return _configuration


def get_db_engine():
    """データベースエンジンを取得（遅延初期化）"""
    global _engine, _connector

    if _engine is None:
        db_user = get_secret('DB_USER')
        db_password = get_secret('DB_PASSWORD')
        db_name = get_secret('DB_NAME')
        instance_connection_name = get_secret('DB_CONNECTION_NAME')

        _connector = Connector()

        def getconn():
            return _connector.connect(
                instance_connection_name,
                "pg8000",
                user=db_user,
                password=db_password,
                db=db_name
            )

        _engine = sqlalchemy.create_engine(
            "postgresql+pg8000://",
            creator=getconn,
        )

    return _engine


@functions_framework.http
def generate_tasks_worker(request: Request):
    """
    非同期タスク生成ワーカー

    Cloud Tasksから呼び出され、タスクを生成してPush通知する
    """

    # リクエストボディを取得
    try:
        request_json = request.get_json(silent=True)
        if not request_json:
            return jsonify({"error": "Invalid request body"}), 400

        user_id = request_json.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        print(f"🔄 タスク生成開始: user_id={user_id}")

        # データベース接続
        engine = get_db_engine()

        # ユーザープロフィールを取得
        with engine.connect() as conn:
            profile_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT relationship, prefecture, municipality, death_date
                    FROM user_profiles
                    WHERE user_id = :user_id
                    """
                ),
                {"user_id": user_id}
            ).fetchone()

            if not profile_data:
                print(f"⚠️ ユーザープロフィールが見つかりません: {user_id}")
                return jsonify({"error": "User profile not found"}), 404

            profile = {
                'relationship': profile_data[0],
                'prefecture': profile_data[1],
                'municipality': profile_data[2],
                'death_date': profile_data[3]
            }

        # タスク生成（この処理に5分程度かかる）
        print(f"🔍 AI駆動型タスク生成中...")
        tasks = generate_basic_tasks(user_id, profile, engine.connect())

        print(f"✅ タスク生成完了: {len(tasks)}件")

        # サマリーメッセージを作成
        municipality = profile['municipality']
        summary_message = get_task_summary_message(tasks, municipality)

        # LINE Push APIで通知
        configuration = get_line_configuration()
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)

            line_bot_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=summary_message)]
                )
            )

        print(f"📤 Push通知送信完了: user_id={user_id}")

        return jsonify({
            "status": "success",
            "user_id": user_id,
            "tasks_count": len(tasks)
        }), 200

    except Exception as e:
        print(f"❌ タスク生成エラー: {e}")
        import traceback
        traceback.print_exc()

        # エラー時もユーザーに通知
        try:
            configuration = get_line_configuration()
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.push_message(
                    PushMessageRequest(
                        to=user_id,
                        messages=[TextMessage(
                            text="⚠️ タスク生成中にエラーが発生しました。\n\nお手数ですが、しばらく時間をおいて再度プロフィール登録をお試しください。"
                        )]
                    )
                )
        except:
            pass

        return jsonify({"error": str(e)}), 500
