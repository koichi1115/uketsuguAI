import os
import json
import hmac
import hashlib
import base64
import functions_framework
from flask import Request, jsonify, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    FlexMessage,
    FlexContainer,
    QuickReply,
    QuickReplyItem,
    MessageAction,
    DatetimePickerAction
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent,
    PostbackEvent
)
from google.cloud import secretmanager
from google.cloud.sql.connector import Connector
from google.cloud import tasks_v2
import sqlalchemy
from datetime import datetime, timezone
from google import genai
from google.genai import types
from flex_messages import create_task_list_flex, create_task_completed_flex
from knowledge_base import search_knowledge
from question_generator import (
    generate_follow_up_questions,
    get_unanswered_questions,
    save_answer,
    check_all_questions_answered,
    get_user_answers,
    format_question_for_line
)
from conversation_flow_manager import ConversationFlowManager, ConversationState
from task_personalizer import generate_personalized_tasks
from task_enhancer import enhance_tasks_with_tips, generate_general_tips_task
from rate_limiter import is_rate_limited
from subscription_manager import SubscriptionManager
from plan_controller import PlanController
from auth_utils import verify_user_ownership, AuthorizationError

# 環境変数からGCP設定を取得
PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
REGION = os.environ.get('GCP_REGION', 'asia-northeast1')
SERVICE_ACCOUNT_EMAIL = os.environ.get(
    'SERVICE_ACCOUNT_EMAIL',
    f'webhook-handler@{PROJECT_ID}.iam.gserviceaccount.com'
)

# グローバル変数（遅延初期化）
_handler = None
_configuration = None
_engine = None
_connector = None
_gemini_client = None
_subscription_manager = None
_plan_controller = None


def get_secret(secret_id: str) -> str:
    """
    Secret Managerからシークレットを取得

    Args:
        secret_id: シークレットID

    Returns:
        シークレット値

    Raises:
        Exception: シークレット取得に失敗した場合
    """
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")

        # ログにシークレット値を出力しない（セキュリティ対策）
        print(f"✅ シークレット取得成功: {secret_id}")
        return secret_value

    except Exception as e:
        # エラー詳細をログに記録（シークレット値は含めない）
        print(f"❌ シークレット取得エラー: secret_id={secret_id}, error={type(e).__name__}")
        # 本番環境では適切なエラーハンドリングを実装
        raise Exception(f"Failed to retrieve secret: {secret_id}") from e


def validate_signature(body: str, signature: str, channel_secret: str) -> bool:
    """署名を検証"""
    hash_value = hmac.new(
        channel_secret.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256
    ).digest()
    calculated_signature = base64.b64encode(hash_value).decode('utf-8')
    return calculated_signature == signature


def get_handler():
    """LINE WebhookHandlerを取得（遅延初期化）"""
    global _handler
    if _handler is None:
        channel_secret = get_secret('LINE_CHANNEL_SECRET')
        _handler = WebhookHandler(channel_secret)

        # イベントハンドラを登録
        @_handler.add(FollowEvent)
        def handle_follow_event(event: FollowEvent):
            handle_follow(event)

        @_handler.add(MessageEvent, message=TextMessageContent)
        def handle_message_event(event: MessageEvent):
            handle_message(event)

        @_handler.add(PostbackEvent)
        def handle_postback_event(event: PostbackEvent):
            handle_postback(event)

    return _handler


def get_configuration():
    """LINE API Configurationを取得（遅延初期化）"""
    global _configuration
    if _configuration is None:
        channel_access_token = get_secret('LINE_CHANNEL_ACCESS_TOKEN')
        _configuration = Configuration(access_token=channel_access_token)
    return _configuration


def get_db_engine():
    """Database Engineを取得（遅延初期化）"""
    global _engine, _connector

    if _engine is None:
        # Database接続設定
        db_connection_name = get_secret('DB_CONNECTION_NAME')
        db_user = get_secret('DB_USER')
        db_password = get_secret('DB_PASSWORD')
        db_name = get_secret('DB_NAME')

        # Cloud SQL Connector
        _connector = Connector()

        def get_db_connection():
            """Cloud SQL接続を取得"""
            conn = _connector.connect(
                db_connection_name,
                "pg8000",
                user=db_user,
                password=db_password,
                db=db_name
            )
            return conn

        # SQLAlchemy エンジン（接続プール設定を追加）
        _engine = sqlalchemy.create_engine(
            "postgresql+pg8000://",
            creator=get_db_connection,
            pool_size=5,           # 同時接続数の上限
            max_overflow=10,       # pool_sizeを超えた場合の追加接続数
            pool_timeout=30,       # 接続取得のタイムアウト（秒）
            pool_recycle=1800,     # 接続の再利用期限（30分）
            pool_pre_ping=True,    # 接続の有効性を事前確認
        )

    return _engine


def get_gemini_client():
    """Gemini Clientを取得（遅延初期化）"""
    global _gemini_client

    if _gemini_client is None:
        gemini_api_key = get_secret('GEMINI_API_KEY')
        _gemini_client = genai.Client(api_key=gemini_api_key)

    return _gemini_client


def get_subscription_manager():
    """Subscription Managerを取得（遅延初期化）"""
    global _subscription_manager

    if _subscription_manager is None:
        engine = get_db_engine()
        stripe_api_key = get_secret('STRIPE_API_KEY').strip()
        _subscription_manager = SubscriptionManager(engine, stripe_api_key)

    return _subscription_manager


def get_plan_controller():
    """Plan Controllerを取得（遅延初期化）"""
    global _plan_controller

    if _plan_controller is None:
        subscription_manager = get_subscription_manager()
        _plan_controller = PlanController(subscription_manager)

    return _plan_controller


def enqueue_task_generation(user_id: str, line_user_id: str):
    """
    Cloud Tasksにタスク生成ジョブを投入

    Args:
        user_id: データベースのユーザーID（UUID）
        line_user_id: LINEユーザーID（Push通知用）
    """
    client = tasks_v2.CloudTasksClient()

    # Cloud Tasksのキュー名
    queue_name = 'task-generation-queue'
    parent = client.queue_path(PROJECT_ID, REGION, queue_name)

    # ワーカーのURL（同じCloud Functionとしてデプロイ）
    worker_url = f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net/task-generator-worker"

    # タスクペイロード（両方のIDを渡す）
    payload = json.dumps({
        'user_id': str(user_id),
        'line_user_id': line_user_id
    }).encode()

    # Cloud Taskを作成（OIDC認証トークン付き）
    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': worker_url,
            'headers': {'Content-Type': 'application/json'},
            'body': payload,
            'oidc_token': {
                'service_account_email': SERVICE_ACCOUNT_EMAIL
            }
        }
    }

    # タスクをキューに追加
    response = client.create_task(request={'parent': parent, 'task': task})
    print(f"📤 Cloud Taskを投入しました: {response.name}")


def enqueue_personalized_task_generation(user_id: str, line_user_id: str):
    """Cloud Tasksに個別タスク生成ジョブを投入"""
    client = tasks_v2.CloudTasksClient()
    queue_name = 'task-generation-queue'
    parent = client.queue_path(PROJECT_ID, REGION, queue_name)

    worker_url = f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net/personalized-tasks-worker"

    payload = json.dumps({
        'user_id': str(user_id),
        'line_user_id': line_user_id
    }).encode()

    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': worker_url,
            'headers': {'Content-Type': 'application/json'},
            'body': payload,
            'oidc_token': {
                'service_account_email': SERVICE_ACCOUNT_EMAIL
            }
        }
    }

    response = client.create_task(request={'parent': parent, 'task': task})
    print(f"📤 個別タスク生成ジョブを投入: {response.name}")


def enqueue_tips_enhancement(user_id: str, line_user_id: str):
    """Cloud TasksにTips収集ジョブを投入"""
    client = tasks_v2.CloudTasksClient()
    queue_name = 'task-generation-queue'
    parent = client.queue_path(PROJECT_ID, REGION, queue_name)

    worker_url = f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net/tips-enhancement-worker"

    payload = json.dumps({
        'user_id': str(user_id),
        'line_user_id': line_user_id
    }).encode()

    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': worker_url,
            'headers': {'Content-Type': 'application/json'},
            'body': payload,
            'oidc_token': {
                'service_account_email': SERVICE_ACCOUNT_EMAIL
            }
        }
    }

    response = client.create_task(request={'parent': parent, 'task': task})
    print(f"📤 Tips収集ジョブを投入: {response.name}")


def enqueue_ai_response_generation(user_id: str, line_user_id: str, user_message: str):
    """Cloud TasksにAI応答生成ジョブを投入"""
    client = tasks_v2.CloudTasksClient()
    # 削除したキュー名は30日間再利用不可のため、v2を使用
    queue_name = 'task-generation-queue-v2'
    parent = client.queue_path(PROJECT_ID, REGION, queue_name)

    worker_url = f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net/ai-response-worker"

    payload = json.dumps({
        'user_id': str(user_id),
        'line_user_id': line_user_id,
        'user_message': user_message
    }).encode()

    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': worker_url,
            'headers': {'Content-Type': 'application/json'},
            'body': payload,
            'oidc_token': {
                'service_account_email': 'webhook-handler@uketsuguai-dev.iam.gserviceaccount.com'
            }
        }
    }

    response = client.create_task(request={'parent': parent, 'task': task})
    print(f"📤 AI応答生成ジョブを投入: {response.name}")


@functions_framework.http
def ai_response_worker(request: Request):
    """非同期AI応答生成ワーカー"""
    try:
        request_json = request.get_json(silent=True)
        if not request_json:
            return jsonify({"error": "Invalid request body"}), 400

        user_id = request_json.get('user_id')
        line_user_id = request_json.get('line_user_id')
        user_message = request_json.get('user_message')

        if not all([user_id, line_user_id, user_message]):
            return jsonify({"error": "user_id, line_user_id, and user_message are required"}), 400

        print(f"🔄 AI応答生成開始: user_id={user_id}")

        # ユーザーメッセージを会話履歴に保存（非同期処理のため明示的に保存）
        engine = get_db_engine()
        with engine.connect() as conn:
            # 最新の会話履歴をチェック（重複回避）
            latest_message = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT message, role
                    FROM conversation_history
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"user_id": user_id}
            ).fetchone()

            # 最新メッセージがユーザーメッセージと異なる場合のみ保存
            if not latest_message or latest_message[0] != user_message or latest_message[1] != 'user':
                conn.execute(
                    sqlalchemy.text(
                        """
                        INSERT INTO conversation_history (user_id, role, message)
                        VALUES (:user_id, 'user', :message)
                        """
                    ),
                    {
                        "user_id": user_id,
                        "message": user_message
                    }
                )
                conn.commit()
                print(f"💾 ユーザーメッセージを会話履歴に保存: {user_message[:50]}...")

        # AI応答を生成
        ai_reply = generate_ai_response(user_id, user_message)

        # LINE Push API で通知
        configuration = get_configuration()
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=line_user_id,
                    messages=[TextMessage(text=ai_reply)]
                )
            )

        print(f"📤 AI応答Push通知送信完了: line_user_id={line_user_id}")
        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"❌ AI応答生成エラー: {e}")
        import traceback
        traceback.print_exc()
        try:
            if 'line_user_id' in locals() and line_user_id:
                configuration = get_configuration()
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=line_user_id,
                            messages=[TextMessage(
                                text="申し訳ございません。AIの応答生成中にエラーが発生しました。"
                            )]
                        )
                    )
        except:
            pass
        return jsonify({"error": str(e)}), 500


@functions_framework.http
def generate_tasks_worker(request: Request):
    """
    非同期タスク生成ワーカー（Step 1: 基本タスク）

    Cloud Tasksから呼び出され、基本タスクを生成してPush通知する
    完了後、追加質問を生成してユーザーに送信
    """
    from task_generator import generate_basic_tasks, get_task_summary_message

    # リクエストボディを取得
    try:
        request_json = request.get_json(silent=True)
        if not request_json:
            return jsonify({"error": "Invalid request body"}), 400

        user_id = request_json.get('user_id')
        line_user_id = request_json.get('line_user_id')

        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        if not line_user_id:
            return jsonify({"error": "line_user_id is required"}), 400

        # データベース接続
        engine = get_db_engine()

        # ユーザー所有権検証
        with engine.connect() as conn:
            try:
                verify_user_ownership(conn, line_user_id, user_id)
            except AuthorizationError as e:
                print(f"❌ 認可エラー: {e}")
                return jsonify({"error": "Unauthorized access"}), 403

        print(f"🔄 Step 1: 基本タスク生成開始: user_id={user_id}")

        # 会話フロー管理初期化
        with engine.connect() as conn:
            flow_manager = ConversationFlowManager(conn)
            flow_manager.set_task_generation_step_status(user_id, 'basic', 'in_progress')

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

        # Step 1: 基本タスク生成
        with engine.connect() as conn:
            tasks = generate_basic_tasks(user_id, profile, conn)

        print(f"✅ Step 1完了: {len(tasks)}件の基本タスクを生成")

        # Step 1完了をマーク
        with engine.connect() as conn:
            flow_manager = ConversationFlowManager(conn)
            flow_manager.set_task_generation_step_status(
                user_id, 'basic', 'completed',
                metadata={'task_count': len(tasks)}
            )

        # 追加質問を生成
        with engine.connect() as conn:
            questions = generate_follow_up_questions(user_id, profile, tasks, conn)

        print(f"✅ 追加質問生成完了: {len(questions)}件")

        # サマリーメッセージ + 追加質問
        municipality = profile['municipality']
        summary_message = get_task_summary_message(tasks, municipality)

        # 追加質問の最初の質問を取得
        with engine.connect() as conn:
            first_question_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT question_text, question_type, options
                    FROM follow_up_questions
                    WHERE user_id = :user_id AND is_answered = false
                    ORDER BY display_order
                    LIMIT 1
                    """
                ),
                {'user_id': user_id}
            ).fetchone()

        # LINE Push API で通知
        configuration = get_configuration()
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)

            messages = [TextMessage(text=summary_message)]

            if first_question_data:
                question_obj = {
                    'question_text': first_question_data[0],
                    'question_type': first_question_data[1],
                    'options': first_question_data[2]
                }
                question_message = format_question_for_line(question_obj)

                # Quick Replyで質問
                quick_reply = QuickReply(
                    items=[
                        QuickReplyItem(action=MessageAction(label="はい", text="はい")),
                        QuickReplyItem(action=MessageAction(label="いいえ", text="いいえ"))
                    ]
                )

                messages.append(
                    TextMessage(
                        text=f"\n\n📝 より詳細なタスクを生成するため、いくつか質問させてください。\n\n{question_message}",
                        quick_reply=quick_reply
                    )
                )

            line_bot_api.push_message(
                PushMessageRequest(
                    to=line_user_id,
                    messages=messages
                )
            )

        print(f"📤 Push通知送信完了: line_user_id={line_user_id}")

        # 会話状態を「追加質問待ち」に設定
        with engine.connect() as conn:
            flow_manager = ConversationFlowManager(conn)
            flow_manager.set_state(
                user_id,
                'awaiting_follow_up_answers',
                {'current_question_index': 0}
            )

        return jsonify({
            "status": "success",
            "user_id": user_id,
            "basic_tasks_count": len(tasks),
            "follow_up_questions_count": len(questions)
        }), 200

    except Exception as e:
        print(f"❌ タスク生成エラー: {e}")
        import traceback
        traceback.print_exc()

        # エラー時はStep 1をfailedにマーク
        if 'user_id' in locals():
            with engine.connect() as conn:
                flow_manager = ConversationFlowManager(conn)
                flow_manager.set_task_generation_step_status(
                    user_id, 'basic', 'failed',
                    error_message=str(e)
                )

        # エラー時もユーザーに通知
        try:
            if 'line_user_id' in locals() and line_user_id:
                configuration = get_configuration()
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=line_user_id,
                            messages=[TextMessage(
                                text="⚠️ タスク生成中にエラーが発生しました。\n\nお手数ですが、しばらく時間をおいて再度プロフィール登録をお試しください。"
                            )]
                        )
                    )
        except:
            pass

        return jsonify({"error": str(e)}), 500


@functions_framework.http
def webhook(request: Request):
    """LINE Webhook エントリーポイント"""

    # 署名検証
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    print(f"Received webhook. Signature: {signature}, Body length: {len(body)}")

    # 手動で署名検証
    channel_secret = get_secret('LINE_CHANNEL_SECRET')
    print(f"Channel Secret length: {len(channel_secret)}")

    is_valid = validate_signature(body, signature, channel_secret)
    print(f"Manual signature validation: {is_valid}")

    try:
        handler = get_handler()
        print(f"Handler initialized successfully")
        handler.handle(body, signature)
        print(f"Handler completed successfully")
    except InvalidSignatureError as e:
        print(f"Invalid signature error: {str(e)}")
        print(f"Body: {body[:200]}")
        print(f"Signature: {signature}")
        abort(400)
    except Exception as e:
        # その他のエラーをログに出力
        print(f"Error handling webhook: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        # LINE の検証リクエストの場合、イベントがなくてもエラーにならないよう 200 を返す
        return jsonify({'status': 'ok'})

    return jsonify({'status': 'ok'})


def handle_follow(event: FollowEvent):
    """友だち追加イベント処理"""
    line_user_id = event.source.user_id
    configuration = get_configuration()
    engine = get_db_engine()

    # ユーザー情報を取得
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        profile = line_bot_api.get_profile(line_user_id)

    # データベースにユーザー登録
    with engine.connect() as conn:
        # 既存ユーザーチェック
        result = conn.execute(
            sqlalchemy.text(
                "SELECT id FROM users WHERE line_user_id = :line_user_id"
            ),
            {"line_user_id": line_user_id}
        ).fetchone()

        if not result:
            # 新規ユーザー登録
            conn.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO users (line_user_id, display_name, status, last_login_at)
                    VALUES (:line_user_id, :display_name, 'active', :last_login_at)
                    """
                ),
                {
                    "line_user_id": line_user_id,
                    "display_name": profile.display_name,
                    "last_login_at": datetime.now(timezone.utc)
                }
            )
            conn.commit()

    # ウェルカムメッセージ
    welcome_message = f"""はじめまして、{profile.display_name}さん。

受け継ぐAIです。
大切な方を亡くされた後の手続きをサポートします。

まず、あなたと故人の関係を選択してください。"""

    # Quick Reply（故人との関係）
    quick_reply = QuickReply(
        items=[
            QuickReplyItem(action=MessageAction(label="父", text="父")),
            QuickReplyItem(action=MessageAction(label="母", text="母")),
            QuickReplyItem(action=MessageAction(label="配偶者", text="配偶者")),
            QuickReplyItem(action=MessageAction(label="兄弟姉妹", text="兄弟姉妹")),
            QuickReplyItem(action=MessageAction(label="祖父母", text="祖父母")),
            QuickReplyItem(action=MessageAction(label="子", text="子")),
            QuickReplyItem(action=MessageAction(label="その他", text="その他"))
        ]
    )

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=welcome_message, quick_reply=quick_reply)]
            )
        )


def handle_message(event: MessageEvent):
    """メッセージイベント処理"""
    line_user_id = event.source.user_id
    user_message = event.message.text
    configuration = get_configuration()
    engine = get_db_engine()

    # ユーザーのlast_login_atを更新
    with engine.connect() as conn:
        conn.execute(
            sqlalchemy.text(
                """
                UPDATE users
                SET last_login_at = :last_login_at
                WHERE line_user_id = :line_user_id
                """
            ),
            {
                "last_login_at": datetime.now(timezone.utc),
                "line_user_id": line_user_id
            }
        )
        conn.commit()

        # ユーザー情報とプロフィール取得
        user_data = conn.execute(
            sqlalchemy.text(
                """
                SELECT u.id, up.relationship, up.prefecture, up.municipality, up.death_date
                FROM users u
                LEFT JOIN user_profiles up ON u.id = up.user_id
                WHERE u.line_user_id = :line_user_id
                """
            ),
            {"line_user_id": line_user_id}
        ).fetchone()

    user_id = user_data[0]

    # ⭐ Phase 1: レート制限チェック
    # ただし、アップグレード関連メッセージと基本コマンドは除外
    bypass_rate_limit_messages = ['アップグレード', '有料プラン', '課金', 'プラン変更', 'ヘルプ', '設定']
    if user_message not in bypass_rate_limit_messages:
        is_limited, limit_message = is_rate_limited(str(user_id), engine)
        if is_limited:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=limit_message)]
                    )
                )
            return  # レート制限超過のため処理終了
    relationship = user_data[1]
    prefecture = user_data[2]
    municipality = user_data[3]
    death_date = user_data[4]

    # 会話履歴を保存
    with engine.connect() as conn:
        conn.execute(
            sqlalchemy.text(
                """
                INSERT INTO conversation_history (user_id, role, message)
                VALUES (:user_id, 'user', :message)
                """
            ),
            {
                "user_id": user_id,
                "message": user_message
            }
        )
        conn.commit()

    # プロフィール収集フロー
    reply_message = process_profile_collection(
        user_id, line_user_id, user_message, relationship, prefecture, municipality, death_date
    )

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 返信メッセージの種類を判定
        if isinstance(reply_message, list):
            # 複数メッセージ（リスト）
            messages = []
            for msg in reply_message:
                if isinstance(msg, dict):
                    if msg.get("type") == "flex":
                        messages.append(FlexMessage(alt_text=msg.get("altText", "メッセージ"), contents=FlexContainer.from_dict(msg["contents"])))
                    else:
                        # Flex Messageのコンテナ（bubble等）
                        alt_text = "メッセージ"
                        if msg.get("header", {}).get("contents"):
                            header_text = msg["header"]["contents"][0].get("text", "")
                            if header_text:
                                alt_text = header_text.replace("📋 ", "").replace("⚙️ ", "")
                        messages.append(FlexMessage(alt_text=alt_text, contents=FlexContainer.from_dict(msg)))
                else:
                    # テキスト
                    messages.append(TextMessage(text=str(msg)))

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=messages
                )
            )
        elif isinstance(reply_message, dict):
            if reply_message.get("type") == "text_with_quick_reply":
                # Quick Reply付きテキストメッセージ
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(
                            text=reply_message["text"],
                            quick_reply=reply_message["quick_reply"]
                        )]
                    )
                )
            else:
                # Flex Message
                # alt_textをヘッダーテキストから取得（なければデフォルト）
                alt_text = "メッセージ"
                if reply_message.get("header", {}).get("contents"):
                    header_text = reply_message["header"]["contents"][0].get("text", "")
                    if header_text:
                        alt_text = header_text.replace("📋 ", "").replace("⚙️ ", "")

                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text=alt_text, contents=FlexContainer.from_dict(reply_message))]
                    )
                )
        else:
            # テキストメッセージ
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_message)]
                )
            )


def process_profile_collection(user_id, line_user_id, message, relationship, prefecture, municipality, death_date):
    """プロフィール収集処理"""
    engine = get_db_engine()

    # 追加質問回答待ち状態のチェック
    with engine.connect() as conn:
        flow_manager = ConversationFlowManager(conn)
        current_state = flow_manager.get_current_state(user_id)

        # 追加質問回答待ち状態の場合
        if current_state == 'awaiting_follow_up_answers':
            # 未回答の質問を取得
            questions = get_unanswered_questions(user_id, conn)

            if questions:
                # 最初の未回答質問に対する回答として保存
                first_question = questions[0]
                save_answer(user_id, first_question['question_key'], message, conn)

                # まだ未回答の質問があるか確認
                remaining_questions = get_unanswered_questions(user_id, conn)

                if remaining_questions:
                    # 次の質問を送信
                    next_question = remaining_questions[0]
                    question_message = format_question_for_line(next_question)

                    quick_reply = QuickReply(
                        items=[
                            QuickReplyItem(action=MessageAction(label="はい", text="はい")),
                            QuickReplyItem(action=MessageAction(label="いいえ", text="いいえ"))
                        ]
                    )

                    return {
                        "type": "text_with_quick_reply",
                        "text": question_message,
                        "quick_reply": quick_reply
                    }
                else:
                    # すべての質問に回答完了
                    # Step 2: 個別タスク生成を開始
                    flow_manager.clear_state(user_id, 'awaiting_follow_up_answers')

                    # Cloud Tasksに個別タスク生成ジョブを投入
                    enqueue_personalized_task_generation(user_id, line_user_id)

                    return """✅ 質問へのご回答ありがとうございました！

🤖 あなたの状況に特化した追加タスクを生成中です...

⏱️ 完了したら通知でお知らせします。"""

    # 編集モードのチェック
    with engine.connect() as conn:
        last_system_message = conn.execute(
            sqlalchemy.text(
                """
                SELECT message
                FROM conversation_history
                WHERE user_id = :user_id AND role = 'system'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id}
        ).fetchone()

        # タスク追加フローのチェック
        if last_system_message and last_system_message[0].startswith('adding_task:'):
            parts = last_system_message[0].split(':')
            adding_step = parts[1]

            # フラグをクリア
            conn.execute(
                sqlalchemy.text(
                    """
                    DELETE FROM conversation_history
                    WHERE user_id = :user_id AND role = 'system' AND message LIKE 'adding_task:%'
                    """
                ),
                {"user_id": user_id}
            )
            conn.commit()

            if adding_step == 'title':
                # タイトル入力後、期限選択へ
                task_title = message

                # タイトルを一時保存
                conn.execute(
                    sqlalchemy.text(
                        """
                        INSERT INTO conversation_history (user_id, role, message)
                        VALUES (:user_id, 'system', :data)
                        """
                    ),
                    {"user_id": user_id, "data": f"adding_task:due_date:{task_title}"}
                )
                conn.commit()

                return {
                    "type": "text_with_quick_reply",
                    "text": f"タスク「{task_title}」の期限を選択してください",
                    "quick_reply": QuickReply(
                        items=[
                            QuickReplyItem(
                                action=DatetimePickerAction(
                                    label="📅 期限を選択",
                                    data="action=add_task_due_date",
                                    mode="date"
                                )
                            ),
                            QuickReplyItem(
                                action=MessageAction(label="期限なし", text="期限なし")
                            )
                        ]
                    )
                }

            elif adding_step == 'due_date':
                # 期限「なし」が選択された場合
                if message == "期限なし":
                    # タイトルを取得
                    if len(parts) >= 3:
                        task_title = ':'.join(parts[2:])

                        # タスクを追加（期限なし）
                        max_order = conn.execute(
                            sqlalchemy.text("SELECT COALESCE(MAX(order_index), 0) FROM tasks WHERE user_id = :user_id"),
                            {"user_id": user_id}
                        ).scalar()

                        conn.execute(
                            sqlalchemy.text(
                                """
                                INSERT INTO tasks (user_id, title, description, category, priority, status, order_index)
                                VALUES (:user_id, :title, :description, :category, :priority, 'pending', :order_index)
                                """
                            ),
                            {
                                "user_id": user_id,
                                "title": task_title,
                                "description": "手動で追加されたタスク",
                                "category": "その他",
                                "priority": "medium",
                                "order_index": max_order + 1
                            }
                        )
                        conn.commit()

                        return f"✅ タスク「{task_title}」を追加しました"
                    else:
                        return "エラーが発生しました。もう一度お試しください。"

        # 編集フローのチェック
        if last_system_message and last_system_message[0].startswith('editing:'):
            editing_field = last_system_message[0].split(':')[1]

            # 編集フラグをクリア
            conn.execute(
                sqlalchemy.text(
                    """
                    DELETE FROM conversation_history
                    WHERE user_id = :user_id AND role = 'system' AND message LIKE 'editing:%'
                    """
                ),
                {"user_id": user_id}
            )
            conn.commit()

            # 各フィールドの更新処理
            if editing_field == 'relationship':
                # 故人との関係を更新
                conn.execute(
                    sqlalchemy.text(
                        """
                        UPDATE user_profiles
                        SET relationship = :relationship
                        WHERE user_id = :user_id
                        """
                    ),
                    {"user_id": user_id, "relationship": message}
                )
                conn.commit()
                return f"✅ 故人との関係を「{message}」に変更しました"

            elif editing_field == 'prefecture':
                # 都道府県選択後、市区町村入力へ
                # 都道府県を一時保存
                conn.execute(
                    sqlalchemy.text(
                        """
                        DELETE FROM conversation_history
                        WHERE user_id = :user_id AND role = 'system' AND message LIKE 'editing:%'
                        """
                    ),
                    {"user_id": user_id}
                )
                conn.execute(
                    sqlalchemy.text(
                        """
                        INSERT INTO conversation_history (user_id, role, message)
                        VALUES (:user_id, 'system', :prefecture_data)
                        """
                    ),
                    {"user_id": user_id, "prefecture_data": f"editing:municipality:{message}"}
                )
                conn.commit()

                return f"{message}の市区町村名を入力してください。\n\n例：新宿区、横浜市"

            elif editing_field == 'municipality':
                # 市区町村入力（都道府県はconversation_historyに保存済み）
                # 都道府県を取得
                parts = last_system_message[0].split(':')
                if len(parts) >= 3:
                    stored_prefecture = parts[2]

                    conn.execute(
                        sqlalchemy.text(
                            """
                            UPDATE user_profiles
                            SET prefecture = :prefecture, municipality = :municipality
                            WHERE user_id = :user_id
                            """
                        ),
                        {"user_id": user_id, "prefecture": stored_prefecture, "municipality": message}
                    )
                    conn.commit()

                    # タスク再生成確認
                    return {
                        "type": "bubble",
                        "body": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": f"✅ お住まいを「{stored_prefecture} {message}」に変更しました",
                                    "wrap": True,
                                    "weight": "bold",
                                    "color": "#17C964"
                                },
                                {
                                    "type": "text",
                                    "text": "住所が変わると、窓口情報や手続き内容が変わる可能性があります。タスクを再生成しますか？",
                                    "wrap": True,
                                    "margin": "lg",
                                    "size": "sm"
                                }
                            ]
                        },
                        "footer": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {
                                    "type": "button",
                                    "action": {
                                        "type": "postback",
                                        "label": "タスクを再生成",
                                        "data": "action=regenerate_tasks",
                                        "displayText": "タスクを再生成"
                                    },
                                    "style": "primary",
                                    "color": "#17C964"
                                },
                                {
                                    "type": "button",
                                    "action": {
                                        "type": "message",
                                        "label": "このまま",
                                        "text": "設定"
                                    },
                                    "style": "link",
                                    "margin": "sm"
                                }
                            ]
                        }
                    }
                else:
                    return "エラーが発生しました。もう一度お試しください。"

        elif last_system_message and last_system_message[0].startswith('editing_memo:'):
            # メモ編集処理
            task_id = last_system_message[0].split(':')[1]

            # 編集フラグをクリア
            conn.execute(
                sqlalchemy.text(
                    """
                    DELETE FROM conversation_history
                    WHERE user_id = :user_id AND role = 'system' AND message LIKE 'editing_memo:%'
                    """
                ),
                {"user_id": user_id}
            )
            conn.commit()

            # メモを保存
            import json
            memo_text = message.strip()

            # メモ削除キーワードのチェック（Issue #16対応）
            delete_keywords = ['削除', 'なし', 'クリア', '消す', 'delete', 'clear', 'none']
            is_delete = memo_text.lower() in delete_keywords

            if memo_text and not is_delete:
                # メモがある場合は保存
                metadata = json.dumps({"memo": memo_text})
            else:
                # 削除キーワードまたは空白の場合はメモを削除
                metadata = json.dumps({"memo": ""})

            conn.execute(
                sqlalchemy.text(
                    """
                    UPDATE tasks
                    SET metadata = CAST(:metadata AS jsonb)
                    WHERE id = :task_id AND user_id = :user_id
                    """
                ),
                {"task_id": task_id, "user_id": user_id, "metadata": metadata}
            )
            conn.commit()

            # 成功メッセージとタスク詳細を返す
            task_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT id, title, description, due_date, priority, category, metadata
                    FROM tasks
                    WHERE id = :task_id AND user_id = :user_id
                    """
                ),
                {"task_id": task_id, "user_id": user_id}
            ).fetchone()

            if task_data:
                from flex_messages import create_task_detail_flex
                success_message = "✅ メモを保存しました" if (memo_text and not is_delete) else "✅ メモを削除しました"
                return [
                    success_message,
                    {
                        "type": "flex",
                        "altText": "タスク詳細",
                        "contents": create_task_detail_flex(task_data)
                    }
                ]
            else:
                return "タスクが見つかりません。"

    # ヘルプと設定は常に表示可能
    if message == 'ヘルプ':
        return get_help_message()
    elif message == '設定':
        return get_settings_message(user_id, relationship, prefecture, municipality, death_date)
    elif message in ['アップグレード', '有料プラン', '課金', 'プラン変更']:
        return handle_upgrade_request(user_id, line_user_id)

    # プロフィールが全て揃っている場合
    if relationship and prefecture and municipality and death_date:
        # 既にタスクが生成されているかチェック
        with engine.connect() as conn:
            task_count = conn.execute(
                sqlalchemy.text(
                    "SELECT COUNT(*) FROM tasks WHERE user_id = :user_id AND is_deleted = false"
                ),
                {"user_id": user_id}
            ).scalar()

            if task_count > 0:
                # タスク生成済み - タスク一覧表示 or タスク完了 or AI会話モード
                if message in ['タスク', 'タスク一覧', 'タスクリスト', 'todo', 'TODO']:
                    return get_task_list_message(user_id)
                elif message == '全タスク':
                    return get_task_list_message(user_id, show_all=True)
                elif message in ['タスク追加', 'タスク追加', '追加']:
                    # タスク追加フローを開始
                    with engine.connect() as conn:
                        conn.execute(
                            sqlalchemy.text(
                                """
                                INSERT INTO conversation_history (user_id, role, message)
                                VALUES (:user_id, 'system', 'adding_task:title')
                                """
                            ),
                            {"user_id": user_id}
                        )
                        conn.commit()
                    return "追加するタスクのタイトルを入力してください"
                elif message == 'ヘルプ':
                    return get_help_message()
                elif message == '設定':
                    return get_settings_message(user_id, relationship, prefecture, municipality, death_date)
                elif '完了' in message and any(c.isdigit() or c in '０１２３４５６７８９' for c in message):
                    # 「完了1」「1完了」「完了１」「１完了」などのパターンをチェック
                    return complete_task(user_id, message)
                else:
                    # AI応答を非同期で生成（Cloud Tasksキュー経由）
                    enqueue_ai_response_generation(user_id, line_user_id, message)
                    return "AIが応答を考えています...\nしばらくお待ちください"
            else:
                # タスク生成をCloud Tasksに投入（非同期）
                enqueue_task_generation(user_id, line_user_id)

                return f"""✅ プロフィール登録が完了しました

🤖 AIがあなた専用のタスクを生成中です...

📍 {prefecture}{municipality}での手続き情報
📅 死亡日: {death_date.strftime('%Y年%m月%d日') if hasattr(death_date, 'strftime') else str(death_date)}

⏱️ 生成には5分程度かかります。完了したら通知でお知らせします。

しばらくお待ちください。"""

    # プロフィール収集中
    with engine.connect() as conn:
        if not relationship:
            # プロフィールが存在するかチェック
            profile_exists = conn.execute(
                sqlalchemy.text(
                    "SELECT id FROM user_profiles WHERE user_id = :user_id"
                ),
                {"user_id": user_id}
            ).fetchone()

            if profile_exists:
                # 既存プロフィールを更新
                conn.execute(
                    sqlalchemy.text(
                        """
                        UPDATE user_profiles
                        SET relationship = :relationship
                        WHERE user_id = :user_id
                        """
                    ),
                    {"user_id": user_id, "relationship": message}
                )
            else:
                # 新規プロフィール作成
                conn.execute(
                    sqlalchemy.text(
                        """
                        INSERT INTO user_profiles (user_id, relationship)
                        VALUES (:user_id, :relationship)
                        """
                    ),
                    {"user_id": user_id, "relationship": message}
                )
            conn.commit()

            # 都道府県選択用のQuick Reply
            prefecture_quick_reply = QuickReply(
                items=[
                    QuickReplyItem(action=MessageAction(label="東京都", text="東京都")),
                    QuickReplyItem(action=MessageAction(label="大阪府", text="大阪府")),
                    QuickReplyItem(action=MessageAction(label="神奈川県", text="神奈川県")),
                    QuickReplyItem(action=MessageAction(label="愛知県", text="愛知県")),
                    QuickReplyItem(action=MessageAction(label="埼玉県", text="埼玉県")),
                    QuickReplyItem(action=MessageAction(label="千葉県", text="千葉県")),
                    QuickReplyItem(action=MessageAction(label="兵庫県", text="兵庫県")),
                    QuickReplyItem(action=MessageAction(label="福岡県", text="福岡県")),
                    QuickReplyItem(action=MessageAction(label="北海道", text="北海道")),
                    QuickReplyItem(action=MessageAction(label="京都府", text="京都府")),
                    QuickReplyItem(action=MessageAction(label="その他", text="その他"))
                ]
            )

            return {
                "type": "text_with_quick_reply",
                "text": "ありがとうございます。\n\n次に、お住まいの都道府県を選択してください。\n（一覧にない場合は直接入力してください）",
                "quick_reply": prefecture_quick_reply
            }

        elif not prefecture:
            # 都道府県を保存
            if message == "その他":
                return "都道府県名を入力してください。\n（例：静岡県）"

            conn.execute(
                sqlalchemy.text(
                    """
                    UPDATE user_profiles
                    SET prefecture = :prefecture
                    WHERE user_id = :user_id
                    """
                ),
                {"user_id": user_id, "prefecture": message}
            )
            conn.commit()
            return "ありがとうございます。\n\n次に、市区町村を教えてください。\n（例：渋谷区）"

        elif not municipality:
            # 市区町村を保存
            conn.execute(
                sqlalchemy.text(
                    """
                    UPDATE user_profiles
                    SET municipality = :municipality
                    WHERE user_id = :user_id
                    """
                ),
                {"user_id": user_id, "municipality": message}
            )
            conn.commit()

            # 死亡日選択用のDatetimepicker Quick Reply
            today = datetime.now().date()

            death_date_quick_reply = QuickReply(
                items=[
                    QuickReplyItem(action=DatetimePickerAction(
                        label="日付を選択",
                        data="action=set_death_date",
                        mode="date",
                        initial=today.isoformat(),
                        max=today.isoformat()
                    ))
                ]
            )

            return {
                "type": "text_with_quick_reply",
                "text": "ありがとうございます。\n\n最後に、故人が亡くなられた日を選択してください。",
                "quick_reply": death_date_quick_reply
            }

        elif not death_date:
            # 死亡日を保存
            try:
                death_dt = datetime.fromisoformat(message).date()

                conn.execute(
                    sqlalchemy.text(
                        """
                        UPDATE user_profiles
                        SET death_date = :death_date
                        WHERE user_id = :user_id
                        """
                    ),
                    {"user_id": user_id, "death_date": death_dt}
                )
                conn.commit()

                # タスク生成をCloud Tasksに投入（非同期）
                enqueue_task_generation(user_id, line_user_id)

                return f"""✅ プロフィール登録が完了しました

🤖 AIがあなた専用のタスクを生成中です...

📍 {prefecture or '（未設定）'}{municipality or '（未設定）'}での手続き情報
📅 死亡日: {death_dt.strftime('%Y年%m月%d日')}

⏱️ 生成には5分程度かかります。完了したら通知でお知らせします。

しばらくお待ちください。"""

            except ValueError:
                return "日付の形式が正しくありません。\nYYYY-MM-DD形式で入力してください。\n（例：2024-01-15）"


def get_task_list_message(user_id: str, show_all: bool = False):
    """タスク一覧をFlex Messageで返す"""
    engine = get_db_engine()

    with engine.connect() as conn:
        tasks = conn.execute(
            sqlalchemy.text(
                """
                SELECT id, title, due_date, status, priority, category, metadata
                FROM tasks
                WHERE user_id = :user_id
                ORDER BY
                    CASE status
                        WHEN 'pending' THEN 1
                        WHEN 'in_progress' THEN 2
                        ELSE 3
                    END,
                    due_date ASC
                """
            ),
            {"user_id": user_id}
        ).fetchall()

    # ⭐ Phase 1: プラン制御 - タスクをプランに応じてフィルタリング
    print(f"📊 Phase 1: タスク数（フィルタリング前）: {len(tasks)}")

    plan_controller = get_plan_controller()
    tasks_as_dict = [
        {
            "id": str(task[0]),
            "title": task[1],
            "due_date": task[2],
            "status": task[3],
            "priority": task[4],
            "category": task[5],
            "metadata": task[6]
        }
        for task in tasks
    ]

    print(f"🔐 Phase 1: プラン制御を実行 (user_id: {user_id})")
    filtered_tasks_dict = plan_controller.filter_tasks_by_plan(str(user_id), tasks_as_dict)
    print(f"📊 Phase 1: タスク数（フィルタリング後）: {len(filtered_tasks_dict)}")

    # 辞書形式をタプル形式に戻す（create_task_list_flexがタプルを期待しているため）
    filtered_tasks = [
        (
            task["id"],
            task["title"],
            task["due_date"],
            task["status"],
            task["priority"],
            task["category"],
            task["metadata"]
        )
        for task in filtered_tasks_dict
    ]

    # Flex Messageを返す（フィルタリング済みタスク）
    return create_task_list_flex(filtered_tasks, show_all=show_all)


def complete_task(user_id: str, message: str) -> str:
    """タスクを完了にする"""
    engine = get_db_engine()

    # タスク番号を抽出（様々なパターンに対応）
    import re

    # 全角数字を半角に変換
    def normalize_number(text):
        zen_to_han = str.maketrans('０１２３４５６７８９', '0123456789')
        return text.translate(zen_to_han)

    normalized_msg = normalize_number(message)

    # 「完了1」「完了 1」「1完了」「1 完了」などのパターンに対応
    patterns = [
        r'完了[\s　]*(\d+)',  # 完了1, 完了 1, 完了　1
        r'(\d+)[\s　]*完了',  # 1完了, 1 完了, 1　完了
    ]

    task_num = None
    for pattern in patterns:
        match = re.search(pattern, normalized_msg)
        if match:
            task_num = int(match.group(1))
            break

    if task_num is None:
        return "タスク番号が正しくありません。\n「完了1」または「1完了」のように番号を指定してください。"

    # 未完了タスクを取得（番号順）
    with engine.connect() as conn:
        pending_tasks = conn.execute(
            sqlalchemy.text(
                """
                SELECT id, title
                FROM tasks
                WHERE user_id = :user_id AND is_deleted = false AND status = 'pending'
                ORDER BY due_date ASC
                """
            ),
            {"user_id": user_id}
        ).fetchall()

        if not pending_tasks:
            return "完了可能なタスクがありません。"

        if task_num < 1 or task_num > len(pending_tasks):
            return f"タスク番号は1〜{len(pending_tasks)}の範囲で指定してください。"

        # 指定されたタスクを完了にする
        task_id, task_title = pending_tasks[task_num - 1]

        conn.execute(
            sqlalchemy.text(
                """
                UPDATE tasks
                SET status = 'completed'
                WHERE id = :task_id AND user_id = :user_id
                """
            ),
            {"task_id": task_id, "user_id": user_id}
        )

        # task_progressに記録
        conn.execute(
            sqlalchemy.text(
                """
                INSERT INTO task_progress (task_id, status, completed_at)
                VALUES (:task_id, 'completed', :completed_at)
                """
            ),
            {
                "task_id": task_id,
                "completed_at": datetime.now(timezone.utc)
            }
        )

        conn.commit()

    return f"✅ 「{task_title}」を完了しました！\n\n他のタスクを確認するには「タスク」と送信してください。"


def generate_ai_response(user_id: str, user_message: str) -> str:
    """Gemini APIを使ってAI応答を生成"""
    engine = get_db_engine()
    client = get_gemini_client()

    # ユーザープロフィールとタスク情報を取得
    with engine.connect() as conn:
        profile_data = conn.execute(
            sqlalchemy.text(
                """
                SELECT up.relationship, up.prefecture, up.municipality, up.death_date
                FROM user_profiles up
                WHERE up.user_id = :user_id
                """
            ),
            {"user_id": user_id}
        ).fetchone()

        # 直近の会話履歴を取得（最新20件 = 約10往復分）
        conversation_history = conn.execute(
            sqlalchemy.text(
                """
                SELECT role, message
                FROM conversation_history
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT 20
                """
            ),
            {"user_id": user_id}
        ).fetchall()

    # システムプロンプト作成
    relationship = profile_data[0] if profile_data else "不明"
    prefecture = profile_data[1] if profile_data else "不明"
    municipality = profile_data[2] if profile_data else "不明"
    death_date = profile_data[3].isoformat() if profile_data and profile_data[3] else "不明"

    system_prompt = f"""あなたは「受け継ぐAI」という死後手続きサポートアシスタントです。

【ユーザー情報】
- 故人との関係: {relationship}
- 住所: {prefecture} {municipality}
- 死亡日: {death_date}

【役割】
- 死後の行政手続きに関する質問に親身に答える
- 手続きの期限や必要書類について具体的にアドバイスする
- 専門的な内容は分かりやすく説明する
- 個人情報（電話番号、マイナンバー等）の入力は避けるよう注意を促す
- 会話の文脈を理解して、前の質問の続きにも適切に答える

【回答スタイル】
- 簡潔で分かりやすく（200文字以内）
- 優しく丁寧な言葉遣い
- 必要に応じて次のステップを提案する
- 「心よりお悔やみ申し上げます」などの前置きは不要
"""

    # 会話履歴を逆順にして（古い順に）プロンプトに追加
    conversation_context = ""
    for i, (role, msg) in enumerate(reversed(conversation_history)):
        if i >= 10:  # 直近10件のみ（約5往復分）
            break
        if role == "user":
            conversation_context += f"ユーザー: {msg}\n"
        elif role == "assistant":
            conversation_context += f"AI: {msg}\n"

    # ナレッジベースから関連情報を取得（RAG）
    knowledge = search_knowledge(user_message)
    knowledge_section = ""
    if knowledge:
        knowledge_section = f"""
【参考情報（行政手続きナレッジベース）】
{knowledge}
"""

    # Gemini APIリクエスト（RAG: ナレッジベース参照）
    prompt = f"""{system_prompt}

【直近の会話】
{conversation_context}
{knowledge_section}
【現在のユーザーメッセージ】
{user_message}

【指示】
上記の参考情報を活用して、正確で具体的な回答をしてください。
特に{prefecture}{municipality}の地域特有の情報があれば補足してください。
参考情報にない内容については、一般的な知識で回答してください。

【あなたの応答】"""

    try:
        # Gemini 2.5 Proで応答生成
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt
        )
        ai_reply = response.text

        # アシスタントの応答を会話履歴に保存
        with engine.connect() as conn:
            conn.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO conversation_history (user_id, role, message)
                    VALUES (:user_id, 'assistant', :message)
                    """
                ),
                {
                    "user_id": user_id,
                    "message": ai_reply
                }
            )
            conn.commit()

        return ai_reply

    except Exception as e:
        print(f"Gemini API error: {str(e)}")
        return "申し訳ございません。現在システムの調子が悪いようです。しばらく経ってから再度お試しください。"


def handle_postback(event: PostbackEvent):
    """ポストバックイベント処理"""
    line_user_id = event.source.user_id
    postback_data = event.postback.data
    configuration = get_configuration()
    engine = get_db_engine()

    # line_user_idからuser_idを取得（認証）
    with engine.connect() as conn:
        user_result = conn.execute(
            sqlalchemy.text("SELECT id FROM users WHERE line_user_id = :line_user_id"),
            {"line_user_id": line_user_id}
        ).fetchone()

        if not user_result:
            # ユーザーが見つからない場合はエラー
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="ユーザー情報が見つかりません。")]
                    )
                )
            return

        user_id = user_result[0]

    # ポストバックデータをパース
    params = dict(param.split('=') for param in postback_data.split('&'))
    action = params.get('action', '')

    if action == 'view_task_detail':
        task_id = params.get('task_id', '')

        # ユーザーIDを取得し、タスク情報を検証付きで取得
        with engine.connect() as conn:
            user_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT u.id
                    FROM users u
                    WHERE u.line_user_id = :line_user_id
                    """
                ),
                {"line_user_id": line_user_id}
            ).fetchone()

            if not user_data:
                reply_message = "ユーザー情報が見つかりません。"
            else:
                user_id = str(user_data[0])

                # タスク情報を取得(user_id検証付き)
                task_data = conn.execute(
                    sqlalchemy.text(
                        """
                        SELECT id, title, description, due_date, priority, category, metadata, user_id
                        FROM tasks
                        WHERE id = :task_id AND user_id = :user_id
                        """
                    ),
                    {"task_id": task_id, "user_id": user_id}
                ).fetchone()

                if not task_data:
                    reply_message = "タスクが見つかりません。"
                else:
                    # タスクのインデックスを取得（無料プランの制限チェックに使用）
                    all_tasks = conn.execute(
                        sqlalchemy.text(
                            """
                            SELECT id
                            FROM tasks
                            WHERE user_id = :user_id AND is_deleted = false AND status = 'pending'
                            ORDER BY due_date ASC
                            """
                        ),
                        {"user_id": user_id}
                    ).fetchall()

                    task_index = next((i for i, t in enumerate(all_tasks) if str(t[0]) == task_id), -1)

                    # プラン制御のチェック
                    plan_controller = get_plan_controller()
                    if not plan_controller.can_access_task_details(user_id, task_index):
                        reply_message = plan_controller.get_upgrade_message()
                    else:
                        # タスク詳細のFlex Messageを生成（user_idフィールドを除外）
                        from flex_messages import create_task_detail_flex
                        reply_message = create_task_detail_flex(task_data[:7])

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)

            # Flex Messageかテキストメッセージか判定
            if isinstance(reply_message, dict):
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text="タスク詳細", contents=FlexContainer.from_dict(reply_message))]
                    )
                )
            else:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_message)]
                    )
                )

    elif action == 'complete_task':
        task_id = params.get('task_id', '')

        # ユーザーIDを取得
        with engine.connect() as conn:
            user_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT u.id
                    FROM users u
                    WHERE u.line_user_id = :line_user_id
                    """
                ),
                {"line_user_id": line_user_id}
            ).fetchone()

            if not user_data:
                reply_message = "ユーザー情報が見つかりません。"
            else:
                user_id = user_data[0]

                # タスク情報を取得
                task_data = conn.execute(
                    sqlalchemy.text(
                        """
                        SELECT title
                        FROM tasks
                        WHERE id = :task_id AND user_id = :user_id
                        """
                    ),
                    {"task_id": task_id, "user_id": user_id}
                ).fetchone()

                if not task_data:
                    reply_message = "タスクが見つかりません。"
                else:
                    task_title = task_data[0]

                    # タスクを完了にする
                    conn.execute(
                        sqlalchemy.text(
                            """
                            UPDATE tasks
                            SET status = 'completed'
                            WHERE id = :task_id AND user_id = :user_id
                            """
                        ),
                        {"task_id": task_id, "user_id": user_id}
                    )

                    # task_progressに記録
                    conn.execute(
                        sqlalchemy.text(
                            """
                            INSERT INTO task_progress (task_id, status, completed_at)
                            VALUES (:task_id, 'completed', :completed_at)
                            """
                        ),
                        {
                            "task_id": task_id,
                            "completed_at": datetime.now(timezone.utc)
                        }
                    )

                    conn.commit()

                    # 更新されたタスク一覧を表示
                    reply_message = get_task_list_message(user_id)

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)

            # Flex Messageかテキストメッセージか判定
            if isinstance(reply_message, dict):
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text="タスク完了", contents=FlexContainer.from_dict(reply_message))]
                    )
                )
            else:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_message)]
                    )
                )

    elif action == 'uncomplete_task':
        task_id = params.get('task_id', '')

        # ユーザーIDを取得
        with engine.connect() as conn:
            user_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT u.id
                    FROM users u
                    WHERE u.line_user_id = :line_user_id
                    """
                ),
                {"line_user_id": line_user_id}
            ).fetchone()

            if not user_data:
                reply_message = "ユーザー情報が見つかりません。"
            else:
                user_id = user_data[0]

                # タスク情報を取得
                task_data = conn.execute(
                    sqlalchemy.text(
                        """
                        SELECT title
                        FROM tasks
                        WHERE id = :task_id AND user_id = :user_id
                        """
                    ),
                    {"task_id": task_id, "user_id": user_id}
                ).fetchone()

                if not task_data:
                    reply_message = "タスクが見つかりません。"
                else:
                    task_title = task_data[0]

                    # タスクを未完了に戻す
                    conn.execute(
                        sqlalchemy.text(
                            """
                            UPDATE tasks
                            SET status = 'pending'
                            WHERE id = :task_id AND user_id = :user_id
                            """
                        ),
                        {"task_id": task_id, "user_id": user_id}
                    )

                    # task_progressに記録
                    conn.execute(
                        sqlalchemy.text(
                            """
                            INSERT INTO task_progress (task_id, status, completed_at)
                            VALUES (:task_id, 'pending', NULL)
                            """
                        ),
                        {"task_id": task_id}
                    )

                    conn.commit()

                    # 更新されたタスク一覧を表示
                    reply_message = get_task_list_message(user_id)

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)

            # Flex Messageかテキストメッセージか判定
            if isinstance(reply_message, dict):
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text="タスク一覧", contents=FlexContainer.from_dict(reply_message))]
                    )
                )
            else:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_message)]
                    )
                )

    elif action == 'set_death_date':
        # Datetimepickerから日付を取得
        selected_date = event.postback.params.get('date')  # YYYY-MM-DD形式

        # ユーザーIDを取得
        with engine.connect() as conn:
            user_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT u.id, up.prefecture, up.municipality
                    FROM users u
                    LEFT JOIN user_profiles up ON u.id = up.user_id
                    WHERE u.line_user_id = :line_user_id
                    """
                ),
                {"line_user_id": line_user_id}
            ).fetchone()

            if not user_data:
                reply_message = "ユーザー情報が見つかりません。"
            else:
                user_id = user_data[0]
                prefecture = user_data[1] or "（未設定）"
                municipality = user_data[2] or "（未設定）"

                # 死亡日を保存
                death_dt = datetime.fromisoformat(selected_date).date()

                conn.execute(
                    sqlalchemy.text(
                        """
                        UPDATE user_profiles
                        SET death_date = :death_date
                        WHERE user_id = :user_id
                        """
                    ),
                    {"user_id": user_id, "death_date": death_dt}
                )
                conn.commit()

                # タスク生成をCloud Tasksに投入（非同期）
                enqueue_task_generation(user_id, line_user_id)

                reply_message = f"""✅ 死亡日を登録しました

🤖 AIがあなた専用のタスクを生成中です...

📍 {prefecture}{municipality}での手続き情報
📅 死亡日: {death_dt.strftime('%Y年%m月%d日')}

⏱️ 生成には5分程度かかります。完了したら通知でお知らせします。

しばらくお待ちください。"""

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_message)]
                )
            )

    elif action == 'edit_relationship':
        # 故人との関係を変更
        quick_reply = QuickReply(
            items=[
                QuickReplyItem(action=MessageAction(label="配偶者", text="配偶者")),
                QuickReplyItem(action=MessageAction(label="子", text="子")),
                QuickReplyItem(action=MessageAction(label="親", text="親")),
                QuickReplyItem(action=MessageAction(label="兄弟姉妹", text="兄弟姉妹")),
                QuickReplyItem(action=MessageAction(label="孫", text="孫")),
                QuickReplyItem(action=MessageAction(label="その他", text="その他"))
            ]
        )

        with engine.connect() as conn:
            # editing_fieldフラグを設定
            conn.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO conversation_history (user_id, role, message)
                    VALUES (
                        (SELECT id FROM users WHERE line_user_id = :line_user_id),
                        'system',
                        'editing:relationship'
                    )
                    """
                ),
                {"line_user_id": line_user_id}
            )
            conn.commit()

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(
                        text="故人との関係を選択してください",
                        quick_reply=quick_reply
                    )]
                )
            )

    elif action == 'edit_address':
        # お住まいを変更（都道府県選択）
        quick_reply = QuickReply(
            items=[
                QuickReplyItem(action=MessageAction(label="東京都", text="東京都")),
                QuickReplyItem(action=MessageAction(label="神奈川県", text="神奈川県")),
                QuickReplyItem(action=MessageAction(label="大阪府", text="大阪府")),
                QuickReplyItem(action=MessageAction(label="愛知県", text="愛知県")),
                QuickReplyItem(action=MessageAction(label="埼玉県", text="埼玉県")),
                QuickReplyItem(action=MessageAction(label="千葉県", text="千葉県")),
                QuickReplyItem(action=MessageAction(label="兵庫県", text="兵庫県")),
                QuickReplyItem(action=MessageAction(label="福岡県", text="福岡県")),
                QuickReplyItem(action=MessageAction(label="北海道", text="北海道")),
                QuickReplyItem(action=MessageAction(label="京都府", text="京都府")),
                QuickReplyItem(action=MessageAction(label="その他", text="その他"))
            ]
        )

        with engine.connect() as conn:
            # editing_fieldフラグを設定（都道府県選択中）
            conn.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO conversation_history (user_id, role, message)
                    VALUES (
                        (SELECT id FROM users WHERE line_user_id = :line_user_id),
                        'system',
                        'editing:prefecture'
                    )
                    """
                ),
                {"line_user_id": line_user_id}
            )
            conn.commit()

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(
                        text="お住まいの都道府県を選択してください",
                        quick_reply=quick_reply
                    )]
                )
            )

    elif action == 'edit_death_date':
        # 死亡日を変更
        with engine.connect() as conn:
            # editing_fieldフラグを設定
            conn.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO conversation_history (user_id, role, message)
                    VALUES (
                        (SELECT id FROM users WHERE line_user_id = :line_user_id),
                        'system',
                        'editing:death_date'
                    )
                    """
                ),
                {"line_user_id": line_user_id}
            )
            conn.commit()

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(
                        text="死亡日を選択してください。\n\n下のボタンからカレンダーが開きます。",
                        quick_reply=QuickReply(
                            items=[
                                QuickReplyItem(
                                    action=DatetimePickerAction(
                                        label="📅 日付を選択",
                                        data="action=update_death_date",
                                        mode="date"
                                    )
                                )
                            ]
                        )
                    )]
                )
            )

    elif action == 'update_death_date':
        # Datetimepickerで選択された死亡日を更新
        selected_date = event.postback.params.get('date')  # YYYY-MM-DD形式

        with engine.connect() as conn:
            user_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT u.id
                    FROM users u
                    WHERE u.line_user_id = :line_user_id
                    """
                ),
                {"line_user_id": line_user_id}
            ).fetchone()

            if not user_data:
                reply_message = "ユーザー情報が見つかりません。"
            else:
                user_id = user_data[0]

                # 死亡日を更新
                from datetime import datetime as dt
                death_dt = dt.fromisoformat(selected_date)

                conn.execute(
                    sqlalchemy.text(
                        """
                        UPDATE user_profiles
                        SET death_date = :death_date
                        WHERE user_id = :user_id
                        """
                    ),
                    {"user_id": user_id, "death_date": death_dt}
                )
                conn.commit()

                # タスク再生成確認
                reply_message = {
                    "type": "bubble",
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {
                                "type": "text",
                                "text": f"✅ 死亡日を{death_dt.strftime('%Y年%m月%d日')}に変更しました",
                                "wrap": True,
                                "weight": "bold",
                                "color": "#17C964"
                            },
                            {
                                "type": "text",
                                "text": "タスクの期限を再計算しますか？",
                                "wrap": True,
                                "margin": "lg"
                            }
                        ]
                    },
                    "footer": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {
                                "type": "button",
                                "action": {
                                    "type": "postback",
                                    "label": "タスクを再生成",
                                    "data": "action=regenerate_tasks",
                                    "displayText": "タスクを再生成"
                                },
                                "style": "primary",
                                "color": "#17C964"
                            },
                            {
                                "type": "button",
                                "action": {
                                    "type": "message",
                                    "label": "このまま",
                                    "text": "設定"
                                },
                                "style": "link",
                                "margin": "sm"
                            }
                        ]
                    }
                }

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            if isinstance(reply_message, dict):
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text="死亡日変更完了", contents=FlexContainer.from_dict(reply_message))]
                    )
                )
            else:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_message)]
                    )
                )

    elif action == 'add_task_due_date':
        # Datetimepickerで選択された期限でタスクを追加
        selected_date = event.postback.params.get('date')  # YYYY-MM-DD形式

        with engine.connect() as conn:
            user_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT u.id
                    FROM users u
                    WHERE u.line_user_id = :line_user_id
                    """
                ),
                {"line_user_id": line_user_id}
            ).fetchone()

            if not user_data:
                reply_message = "ユーザー情報が見つかりません。"
            else:
                user_id = user_data[0]

                # タイトルを取得
                last_system_message = conn.execute(
                    sqlalchemy.text(
                        """
                        SELECT message
                        FROM conversation_history
                        WHERE user_id = :user_id AND role = 'system' AND message LIKE 'adding_task:due_date:%'
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"user_id": user_id}
                ).fetchone()

                if last_system_message:
                    parts = last_system_message[0].split(':')
                    if len(parts) >= 3:
                        task_title = ':'.join(parts[2:])

                        # フラグをクリア
                        conn.execute(
                            sqlalchemy.text(
                                """
                                DELETE FROM conversation_history
                                WHERE user_id = :user_id AND role = 'system' AND message LIKE 'adding_task:%'
                                """
                            ),
                            {"user_id": user_id}
                        )

                        # タスクを追加
                        from datetime import datetime as dt
                        due_dt = dt.fromisoformat(selected_date)

                        max_order = conn.execute(
                            sqlalchemy.text("SELECT COALESCE(MAX(order_index), 0) FROM tasks WHERE user_id = :user_id"),
                            {"user_id": user_id}
                        ).scalar()

                        conn.execute(
                            sqlalchemy.text(
                                """
                                INSERT INTO tasks (user_id, title, description, category, priority, due_date, status, order_index)
                                VALUES (:user_id, :title, :description, :category, :priority, :due_date, 'pending', :order_index)
                                """
                            ),
                            {
                                "user_id": user_id,
                                "title": task_title,
                                "description": "手動で追加されたタスク",
                                "category": "その他",
                                "priority": "medium",
                                "due_date": due_dt,
                                "order_index": max_order + 1
                            }
                        )
                        conn.commit()

                        reply_message = f"✅ タスク「{task_title}」を追加しました\n期限: {due_dt.strftime('%Y年%m月%d日')}"
                    else:
                        reply_message = "エラーが発生しました。もう一度お試しください。"
                else:
                    reply_message = "エラーが発生しました。もう一度お試しください。"

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_message)]
                )
            )

    elif action == 'edit_memo':
        # メモ編集モードに入る
        task_id = event.postback.data.split('task_id=')[1]

        with engine.connect() as conn:
            user_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT u.id
                    FROM users u
                    WHERE u.line_user_id = :line_user_id
                    """
                ),
                {"line_user_id": line_user_id}
            ).fetchone()

            if user_data:
                user_id = user_data[0]

                # editing_memoフラグを設定
                conn.execute(
                    sqlalchemy.text(
                        """
                        INSERT INTO conversation_history (user_id, role, message)
                        VALUES (:user_id, 'system', :data)
                        """
                    ),
                    {"user_id": user_id, "data": f"editing_memo:{task_id}"}
                )
                conn.commit()

                reply_message = "メモを入力してください。\n\nメモを削除する場合は「削除」と送信してください。"
            else:
                reply_message = "ユーザー情報が見つかりません。"

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_message)]
                )
            )

    elif action == 'regenerate_tasks':
        # 既存タスクを削除してタスクを再生成
        with engine.connect() as conn:
            user_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT u.id
                    FROM users u
                    WHERE u.line_user_id = :line_user_id
                    """
                ),
                {"line_user_id": line_user_id}
            ).fetchone()

            if user_data:
                user_id = user_data[0]

                # 既存タスクを削除
                conn.execute(
                    sqlalchemy.text("DELETE FROM tasks WHERE user_id = :user_id"),
                    {"user_id": user_id}
                )
                conn.commit()

                # タスク再生成をCloud Tasksに投入
                enqueue_task_generation(user_id, line_user_id)

                reply_message = """✅ タスクを再生成しています

🤖 AIがあなた専用のタスクを生成中です...

⏱️ 生成には5分程度かかります。完了したら通知でお知らせします。"""
            else:
                reply_message = "ユーザー情報が見つかりません。"

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_message)]
                )
            )

    elif action == 'view_subscription_status':
        # サブスクリプションステータスの確認（Issue #19対応）
        with engine.connect() as conn:
            user_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT id, subscription_status, subscription_plan, subscription_start_date, subscription_end_date
                    FROM users
                    WHERE line_user_id = :line_user_id
                    """
                ),
                {"line_user_id": line_user_id}
            ).fetchone()

            if not user_data:
                reply_message = "ユーザー情報が見つかりません。"
            else:
                user_id, status, plan, start_date, end_date = user_data

                # サブスクリプションステータスに応じたメッセージを生成
                if status == 'active':
                    status_emoji = "✅"
                    status_text = "有効"
                    plan_text = plan or "スタンダードプラン"
                    start_text = start_date.strftime("%Y年%m月%d日") if start_date else "不明"
                    end_text = end_date.strftime("%Y年%m月%d日") if end_date else "継続中"

                    reply_message = f"""{status_emoji} サブスクリプションステータス

【現在の状態】
ステータス: {status_text}
プラン: {plan_text}
開始日: {start_text}
次回更新日: {end_text}

サブスクリプションは正常に継続されています。"""

                elif status == 'cancelled':
                    status_emoji = "⚠️"
                    status_text = "解約済み"
                    end_text = end_date.strftime("%Y年%m月%d日") if end_date else "不明"

                    reply_message = f"""{status_emoji} サブスクリプションステータス

【現在の状態】
ステータス: {status_text}
利用可能期限: {end_text}

サブスクリプションは解約されています。
期限まではサービスをご利用いただけます。"""

                else:
                    # 未契約またはその他の状態
                    reply_message = """💡 サブスクリプション未契約

現在サブスクリプションに未登録です。
プレミアム機能をご利用いただくには、サブスクリプションへの登録が必要です。

詳細はウェブサイトをご確認ください。"""

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_message)]
                )
            )

    elif action == 'cancel_subscription':
        # サブスクリプション解約（Issue #19対応）
        with engine.connect() as conn:
            user_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT id, subscription_status
                    FROM users
                    WHERE line_user_id = :line_user_id
                    """
                ),
                {"line_user_id": line_user_id}
            ).fetchone()

            if not user_data:
                reply_message = "ユーザー情報が見つかりません。"
            else:
                user_id, status = user_data

                if status == 'active':
                    # 解約確認メッセージを送信
                    reply_message = {
                        "type": "bubble",
                        "body": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": "⚠️ サブスクリプション解約",
                                    "weight": "bold",
                                    "size": "lg",
                                    "color": "#FF6B6B"
                                },
                                {
                                    "type": "text",
                                    "text": "本当に解約しますか？",
                                    "wrap": True,
                                    "margin": "md"
                                },
                                {
                                    "type": "text",
                                    "text": "• 現在の契約期間終了後、サービスが利用できなくなります\n• タスク生成などの機能が制限されます",
                                    "wrap": True,
                                    "size": "sm",
                                    "color": "#999999",
                                    "margin": "md"
                                }
                            ]
                        },
                        "footer": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {
                                    "type": "button",
                                    "action": {
                                        "type": "postback",
                                        "label": "解約を確定する",
                                        "data": "action=confirm_cancel_subscription",
                                        "displayText": "解約を確定"
                                    },
                                    "style": "primary",
                                    "color": "#FF6B6B"
                                },
                                {
                                    "type": "button",
                                    "action": {
                                        "type": "message",
                                        "label": "キャンセル",
                                        "text": "設定"
                                    },
                                    "style": "link",
                                    "margin": "sm"
                                }
                            ]
                        }
                    }
                else:
                    reply_message = "現在有効なサブスクリプションがありません。"

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            if isinstance(reply_message, dict):
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            FlexMessage(
                                alt_text="サブスクリプション解約確認",
                                contents=FlexContainer.from_dict(reply_message)
                            )
                        ]
                    )
                )
            else:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_message)]
                    )
                )

    elif action == 'confirm_cancel_subscription':
        # サブスクリプション解約確定（Issue #19対応）
        with engine.connect() as conn:
            user_data = conn.execute(
                sqlalchemy.text(
                    """
                    SELECT id, subscription_end_date
                    FROM users
                    WHERE line_user_id = :line_user_id AND subscription_status = 'active'
                    """
                ),
                {"line_user_id": line_user_id}
            ).fetchone()

            if not user_data:
                reply_message = "有効なサブスクリプションが見つかりません。"
            else:
                user_id, end_date = user_data

                # サブスクリプションステータスを解約に変更
                conn.execute(
                    sqlalchemy.text(
                        """
                        UPDATE users
                        SET subscription_status = 'cancelled'
                        WHERE id = :user_id
                        """
                    ),
                    {"user_id": user_id}
                )
                conn.commit()

                end_text = end_date.strftime("%Y年%m月%d日") if end_date else "契約期間終了時"

                reply_message = f"""✅ サブスクリプションを解約しました

{end_text}までサービスをご利用いただけます。

ご利用ありがとうございました。
またのご利用をお待ちしております。"""

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_message)]
                )
            )

    else:
        # 未知のアクション
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=f"不明なアクション: {action}")]
                )
            )


@functions_framework.http
def personalized_tasks_worker(request: Request):
    """
    Step 2: 個別タスク生成ワーカー

    Cloud Tasksから呼び出され、追加質問の回答に基づいて
    個別タスクを生成する
    """
    try:
        request_json = request.get_json(silent=True)
        if not request_json:
            return jsonify({"error": "Invalid request body"}), 400

        user_id = request_json.get('user_id')
        line_user_id = request_json.get('line_user_id')

        if not user_id or not line_user_id:
            return jsonify({"error": "user_id and line_user_id are required"}), 400

        engine = get_db_engine()

        # ユーザー所有権検証
        with engine.connect() as conn:
            try:
                verify_user_ownership(conn, line_user_id, user_id)
            except AuthorizationError as e:
                print(f"❌ 認可エラー: {e}")
                return jsonify({"error": "Unauthorized access"}), 403

        print(f"🔄 Step 2: 個別タスク生成開始: user_id={user_id}")

        # Step 2開始をマーク
        with engine.connect() as conn:
            flow_manager = ConversationFlowManager(conn)
            flow_manager.set_task_generation_step_status(user_id, 'personalized', 'in_progress')

        # プロフィールと追加回答を取得
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

            profile = {
                'relationship': profile_data[0],
                'prefecture': profile_data[1],
                'municipality': profile_data[2],
                'death_date': profile_data[3]
            }

            additional_answers = get_user_answers(user_id, conn)

        # Step 2: 個別タスク生成
        with engine.connect() as conn:
            personalized_tasks = generate_personalized_tasks(
                user_id, profile, additional_answers, conn
            )

        print(f"✅ Step 2完了: {len(personalized_tasks)}件の個別タスクを生成")

        # Step 2完了をマーク
        with engine.connect() as conn:
            flow_manager = ConversationFlowManager(conn)
            flow_manager.set_task_generation_step_status(
                user_id, 'personalized', 'completed',
                metadata={'task_count': len(personalized_tasks)}
            )

        # LINE通知
        configuration = get_configuration()
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=line_user_id,
                    messages=[TextMessage(
                        text=f"✅ あなた専用の追加タスクを{len(personalized_tasks)}件生成しました！\n\n「タスク」と送信して確認してください。"
                    )]
                )
            )

        # Step 3: Tips収集をバックグラウンドで開始
        enqueue_tips_enhancement(user_id, line_user_id)

        return jsonify({
            "status": "success",
            "user_id": user_id,
            "personalized_tasks_count": len(personalized_tasks)
        }), 200

    except Exception as e:
        print(f"❌ 個別タスク生成エラー: {e}")
        import traceback
        traceback.print_exc()

        if 'user_id' in locals():
            with engine.connect() as conn:
                flow_manager = ConversationFlowManager(conn)
                flow_manager.set_task_generation_step_status(
                    user_id, 'personalized', 'failed',
                    error_message=str(e)
                )

        return jsonify({"error": str(e)}), 500


@functions_framework.http
def tips_enhancement_worker(request: Request):
    """
    Step 3: Tips収集・拡張ワーカー

    Cloud Tasksから呼び出され、既存タスクにSNS・ブログから
    収集したTipsを追加する
    """
    try:
        request_json = request.get_json(silent=True)
        if not request_json:
            return jsonify({"error": "Invalid request body"}), 400

        user_id = request_json.get('user_id')
        line_user_id = request_json.get('line_user_id')

        if not user_id or not line_user_id:
            return jsonify({"error": "user_id and line_user_id are required"}), 400

        engine = get_db_engine()

        # ユーザー所有権検証
        with engine.connect() as conn:
            try:
                verify_user_ownership(conn, line_user_id, user_id)
            except AuthorizationError as e:
                print(f"❌ 認可エラー: {e}")
                return jsonify({"error": "Unauthorized access"}), 403

        print(f"🔄 Step 3: Tips収集開始: user_id={user_id}")

        # Step 3開始をマーク
        with engine.connect() as conn:
            flow_manager = ConversationFlowManager(conn)
            flow_manager.set_task_generation_step_status(user_id, 'enhanced', 'in_progress')

        # プロフィール取得
        with engine.connect() as conn:
            profile_data = conn.execute(
                sqlalchemy.text(
                    "SELECT relationship, prefecture, municipality, death_date FROM user_profiles WHERE user_id = :user_id"
                ),
                {"user_id": user_id}
            ).fetchone()

            profile = {
                'relationship': profile_data[0],
                'prefecture': profile_data[1],
                'municipality': profile_data[2],
                'death_date': profile_data[3]
            }

        # Step 3: Tips収集・拡張
        with engine.connect() as conn:
            stats = enhance_tasks_with_tips(user_id, conn)
            generate_general_tips_task(user_id, profile, conn)

        print(f"✅ Step 3完了: {stats['enhanced_count']}件のタスクに{stats['new_tips_count']}個のTipsを追加")

        # Step 3完了をマーク
        with engine.connect() as conn:
            flow_manager = ConversationFlowManager(conn)
            flow_manager.set_task_generation_step_status(
                user_id, 'enhanced', 'completed',
                metadata=stats
            )

        # LINE通知
        configuration = get_configuration()
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=line_user_id,
                    messages=[TextMessage(
                        text=f"💡 タスクに実用的なTipsを追加しました！\n\n体験談や裏技を参考にして、スムーズに手続きを進めてください。"
                    )]
                )
            )

        return jsonify({
            "status": "success",
            "user_id": user_id,
            "enhanced_count": stats['enhanced_count'],
            "new_tips_count": stats['new_tips_count']
        }), 200

    except Exception as e:
        print(f"❌ Tips収集エラー: {e}")
        import traceback
        traceback.print_exc()

        if 'user_id' in locals():
            with engine.connect() as conn:
                flow_manager = ConversationFlowManager(conn)
                flow_manager.set_task_generation_step_status(
                    user_id, 'enhanced', 'failed',
                    error_message=str(e)
                )

        return jsonify({"error": str(e)}), 500


@functions_framework.http
def stripe_webhook(request: Request):
    """
    Stripe Webhookエンドポイント

    決済完了やサブスクリプションキャンセルなどのイベントを受け取る
    """
    try:
        # Stripe署名検証用のシークレットを取得
        webhook_secret = get_secret('STRIPE_WEBHOOK_SECRET').strip()

        # リクエストボディと署名を取得
        payload = request.get_data(as_text=True)
        sig_header = request.headers.get('Stripe-Signature')

        if not sig_header:
            print("❌ Stripe署名ヘッダーがありません")
            return jsonify({"error": "No signature header"}), 400

        # Stripe署名を検証してイベントを構築
        import stripe
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except stripe.error.SignatureVerificationError as e:
            print(f"❌ Stripe署名検証エラー: {str(e)}")
            return jsonify({"error": "Invalid signature"}), 400

        # イベントタイプに応じて処理
        event_type = event['type']
        print(f"📬 Stripe Webhookイベント受信: {event_type}")

        subscription_manager = get_subscription_manager()

        if event_type == 'checkout.session.completed':
            # 決済完了イベント
            session = event['data']['object']
            subscription_manager.handle_checkout_completed(session)
            print(f"✅ Checkout完了処理: user_id={session['metadata'].get('user_id')}")

        elif event_type == 'customer.subscription.deleted':
            # サブスクリプションキャンセルイベント
            subscription = event['data']['object']
            subscription_manager.handle_subscription_deleted(subscription)
            print(f"✅ サブスクリプション削除処理: subscription_id={subscription['id']}")

        else:
            # その他のイベントはログのみ
            print(f"ℹ️ 未処理のイベントタイプ: {event_type}")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"❌ Stripe Webhookエラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def handle_upgrade_request(user_id: str, line_user_id: str):
    """アップグレードリクエストを処理"""
    engine = get_db_engine()
    subscription_manager = get_subscription_manager()
    plan_controller = get_plan_controller()

    # 現在のプラン状態を確認
    if subscription_manager.is_premium_user(str(user_id)):
        # 既に有料プランの場合
        subscription = subscription_manager.get_user_subscription(str(user_id))
        return f"""✅ 有料プラン加入中です

現在のプラン: β版プラン（月額500円）
ステータス: {subscription['status']}

有料プランの特典：
✅ すべてのタスクを閲覧
✅ 独自タスクの追加・編集・削除
✅ リマインダー機能（準備中）
✅ グループLINE対応（準備中）

プランの管理は「設定」から行えます。"""

    # 無料プランの場合、Stripe Checkoutセッションを作成
    try:
        # 決済完了後のリダイレクトURL
        # Stripeの制約でhttps://が必要なため、一時的にダミーのURLを使用
        # 実際の本番環境では、専用のランディングページを用意するのが望ましい
        import urllib.parse
        base_url = "https://line.me/R/oaMessage/@yourbotid/"
        success_message = urllib.parse.quote("感謝します！有料プラン登録が完了しました")
        cancel_message = urllib.parse.quote("キャンセルされました")

        success_url = f"{base_url}?{success_message}"
        cancel_url = f"{base_url}?{cancel_message}"

        checkout_url = subscription_manager.create_checkout_session(
            user_id=str(user_id),
            line_user_id=line_user_id,
            success_url=success_url,
            cancel_url=cancel_url
        )

        return f"""💎 有料プランへのアップグレード

β版プラン: 月額500円（税込）

【特典】
✅ すべてのタスクを閲覧
✅ 独自タスクの追加・編集・削除
✅ リマインダー機能（準備中）
✅ グループLINE対応（準備中）

以下のリンクから決済画面にアクセスしてください：
{checkout_url}

※クレジットカード決済（Stripe）を利用します
※テスト環境では実際の決済は行われません"""

    except Exception as e:
        print(f"Stripe Checkoutセッション作成エラー: {str(e)}")
        return """申し訳ございません。現在アップグレード処理に問題が発生しています。

しばらく経ってから再度お試しください。
問題が続く場合は、お問い合わせください。

📞 お問い合わせ: ko_15_ko_15-m1@yahoo.co.jp"""


def get_help_message() -> str:
    """ヘルプメッセージを生成"""
    return """【受け継ぐAI 使い方ガイド】

🤖 **受け継ぐAIとは**
大切な方が亡くなられた後の行政手続きをサポートするLINE Botです。

📋 **主な機能**
1. タスク管理
   - 必要な手続きを自動でリストアップ
   - 期限・優先度を表示
   - 完了したタスクにチェック

2. AI相談
   - 手続きに関する質問に回答
   - 行政ナレッジベースを活用

3. リッチメニュー
   - タスク一覧：やるべきことを確認
   - AI相談：質問や相談
   - 設定：プロフィール確認
   - ヘルプ：このメッセージ

📞 **お問い合わせ**
ko_15_ko_15-m1@yahoo.co.jp

💡 **ヒント**
- 「タスク」でタスク一覧を表示
- 「全タスク」で完了済み含む全て表示
- 質問は自由に入力してください"""


def get_plan_info_section(user_id: str):
    """プラン情報セクションを生成"""
    subscription_manager = get_subscription_manager()
    plan_controller = get_plan_controller()

    is_premium = subscription_manager.is_premium_user(str(user_id))

    if is_premium:
        # 有料プランの場合
        subscription = subscription_manager.get_user_subscription(str(user_id))
        plan_text = "β版プラン（月額500円）"
        status_text = "✅ アクティブ"
        button_label = "プラン管理"
        button_text = "プラン変更"
    else:
        # 無料プランの場合
        plan_text = "無料プラン"
        status_text = "⚠️ 2タスクまで閲覧可能"
        button_label = "アップグレード"
        button_text = "アップグレード"

    return {
        "type": "box",
        "layout": "vertical",
        "contents": [
            {
                "type": "text",
                "text": "💎 プラン",
                "size": "sm",
                "color": "#999999",
                "weight": "bold"
            },
            {
                "type": "text",
                "text": plan_text,
                "size": "md",
                "color": "#333333",
                "wrap": True,
                "margin": "sm"
            },
            {
                "type": "text",
                "text": status_text,
                "size": "xs",
                "color": "#17C964" if is_premium else "#F5A623",
                "wrap": True,
                "margin": "xs"
            },
            {
                "type": "button",
                "action": {
                    "type": "message",
                    "label": button_label,
                    "text": button_text
                },
                "style": "primary" if not is_premium else "link",
                "color": "#17C964" if not is_premium else None,
                "height": "sm",
                "margin": "md"
            }
        ],
        "paddingAll": "12px",
        "backgroundColor": "#FAFAFA",
        "cornerRadius": "8px",
        "margin": "md"
    }


def get_settings_message(user_id: str, relationship: str, prefecture: str, municipality: str, death_date):
    """設定メッセージを生成（FlexMessage形式）"""
    # 死亡日をフォーマット
    death_date_str = death_date.strftime("%Y年%m月%d日") if death_date else "未設定"

    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "⚙️ 設定",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#333333"
                }
            ],
            "paddingAll": "15px",
            "backgroundColor": "#F7F7F7"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                # 故人との関係
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "👤 故人との関係",
                            "size": "sm",
                            "color": "#999999",
                            "weight": "bold"
                        },
                        {
                            "type": "text",
                            "text": relationship or "未設定",
                            "size": "md",
                            "color": "#333333",
                            "wrap": True,
                            "margin": "sm"
                        },
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "変更",
                                "data": "action=edit_relationship",
                                "displayText": "故人との関係を変更"
                            },
                            "style": "link",
                            "height": "sm",
                            "margin": "sm"
                        }
                    ],
                    "paddingAll": "12px",
                    "backgroundColor": "#FAFAFA",
                    "cornerRadius": "8px"
                },
                # お住まい
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "📍 お住まい",
                            "size": "sm",
                            "color": "#999999",
                            "weight": "bold"
                        },
                        {
                            "type": "text",
                            "text": f"{prefecture or '未設定'} {municipality or ''}",
                            "size": "md",
                            "color": "#333333",
                            "wrap": True,
                            "margin": "sm"
                        },
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "変更",
                                "data": "action=edit_address",
                                "displayText": "お住まいを変更"
                            },
                            "style": "link",
                            "height": "sm",
                            "margin": "sm"
                        }
                    ],
                    "paddingAll": "12px",
                    "backgroundColor": "#FAFAFA",
                    "cornerRadius": "8px",
                    "margin": "md"
                },
                # 死亡日
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "📅 死亡日",
                            "size": "sm",
                            "color": "#999999",
                            "weight": "bold"
                        },
                        {
                            "type": "text",
                            "text": death_date_str,
                            "size": "md",
                            "color": "#333333",
                            "wrap": True,
                            "margin": "sm"
                        },
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "変更",
                                "data": "action=edit_death_date",
                                "displayText": "死亡日を変更"
                            },
                            "style": "link",
                            "height": "sm",
                            "margin": "sm"
                        }
                    ],
                    "paddingAll": "12px",
                    "backgroundColor": "#FAFAFA",
                    "cornerRadius": "8px",
                    "margin": "md"
                },
                # プラン情報を追加
                get_plan_info_section(user_id),
                # サブスクリプション管理（Issue #19対応）
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "💳 サブスクリプション",
                            "size": "sm",
                            "color": "#999999",
                            "weight": "bold"
                        },
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "ステータスを確認",
                                "data": "action=view_subscription_status",
                                "displayText": "サブスクリプションステータスを確認"
                            },
                            "style": "link",
                            "height": "sm",
                            "margin": "sm"
                        },
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "解約手続き",
                                "data": "action=cancel_subscription",
                                "displayText": "サブスクリプションを解約"
                            },
                            "style": "link",
                            "height": "sm",
                            "margin": "sm",
                            "color": "#FF6B6B"
                        }
                    ],
                    "paddingAll": "12px",
                    "backgroundColor": "#FAFAFA",
                    "cornerRadius": "8px",
                    "margin": "md"
                },
                # 注意書き
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "💡 死亡日を変更すると、タスクの期限も再計算されます。",
                            "size": "xs",
                            "color": "#999999",
                            "wrap": True
                        }
                    ],
                    "margin": "lg"
                }
            ],
            "paddingAll": "20px"
        }
    }
