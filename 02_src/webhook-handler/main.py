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
    TextMessage,
    FlexMessage,
    FlexContainer
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent,
    PostbackEvent
)
from google.cloud import secretmanager
from google.cloud.sql.connector import Connector
import sqlalchemy
from datetime import datetime, timezone
import google.generativeai as genai

# 環境変数からGCP設定を取得
PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
REGION = os.environ.get('GCP_REGION', 'asia-northeast1')

# グローバル変数（遅延初期化）
_handler = None
_configuration = None
_engine = None
_connector = None
_gemini_model = None


def get_secret(secret_id: str) -> str:
    """Secret Managerからシークレットを取得"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


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

        # SQLAlchemy エンジン
        _engine = sqlalchemy.create_engine(
            "postgresql+pg8000://",
            creator=get_db_connection,
        )

    return _engine


def get_gemini_model():
    """Gemini Modelを取得（遅延初期化）"""
    global _gemini_model

    if _gemini_model is None:
        gemini_api_key = get_secret('GEMINI_API_KEY')
        genai.configure(api_key=gemini_api_key)
        _gemini_model = genai.GenerativeModel('gemini-2.0-flash-exp')

    return _gemini_model


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

まずは、以下の情報を教えてください：
1. あなたと故人の関係
2. お住まいの都道府県・市区町村
3. 故人が亡くなられた日

※個人情報の入力にご注意ください
電話番号、マイナンバー等は入力しないでください"""

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=welcome_message)]
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
    reply_text = process_profile_collection(
        user_id, user_message, relationship, prefecture, municipality, death_date
    )

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


def process_profile_collection(user_id, message, relationship, prefecture, municipality, death_date):
    """プロフィール収集処理"""
    from task_generator import generate_basic_tasks, get_task_summary_message

    engine = get_db_engine()

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
                # タスク生成済み - AI会話モード
                return generate_ai_response(user_id, message)
            else:
                # タスク生成
                with engine.connect() as conn:
                    tasks = generate_basic_tasks(
                        user_id,
                        {
                            'death_date': death_date,
                            'prefecture': prefecture,
                            'municipality': municipality
                        },
                        conn
                    )

                return get_task_summary_message(tasks, municipality)

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
            return "ありがとうございます。\n\n次に、お住まいの都道府県と市区町村を教えてください。\n（例：東京都 渋谷区）"

        elif not prefecture or not municipality:
            # 都道府県・市区町村を解析して保存
            parts = message.replace('　', ' ').split()
            if len(parts) >= 2:
                pref = parts[0]
                muni = parts[1]

                conn.execute(
                    sqlalchemy.text(
                        """
                        UPDATE user_profiles
                        SET prefecture = :prefecture, municipality = :municipality
                        WHERE user_id = :user_id
                        """
                    ),
                    {"user_id": user_id, "prefecture": pref, "municipality": muni}
                )
                conn.commit()
                return f"ありがとうございます。\n\n最後に、故人が亡くなられた日を教えてください。\n（例：2024-01-15）"
            else:
                return "都道府県と市区町村を教えてください。\n（例：東京都 渋谷区）"

        elif not death_date:
            # 死亡日を保存
            try:
                from datetime import datetime
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

                # タスク生成
                tasks = generate_basic_tasks(
                    user_id,
                    {
                        'death_date': death_dt,
                        'prefecture': prefecture or '（未設定）',
                        'municipality': municipality or '（未設定）'
                    },
                    conn
                )

                return get_task_summary_message(tasks, municipality or '（未設定）')

            except ValueError:
                return "日付の形式が正しくありません。\nYYYY-MM-DD形式で入力してください。\n（例：2024-01-15）"


def generate_ai_response(user_id: str, user_message: str) -> str:
    """Gemini APIを使ってAI応答を生成"""
    engine = get_db_engine()
    model = get_gemini_model()

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

        # 直近の会話履歴を取得（最新10件）
        conversation_history = conn.execute(
            sqlalchemy.text(
                """
                SELECT role, message
                FROM conversation_history
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT 10
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

【回答スタイル】
- 簡潔で分かりやすく（200文字以内）
- 優しく丁寧な言葉遣い
- 必要に応じて次のステップを提案する
"""

    # 会話履歴を逆順にして（古い順に）プロンプトに追加
    conversation_context = ""
    for i, (role, msg) in enumerate(reversed(conversation_history)):
        if i >= 5:  # 直近5件のみ
            break
        if role == "user":
            conversation_context += f"ユーザー: {msg}\n"
        elif role == "assistant":
            conversation_context += f"AI: {msg}\n"

    # Gemini APIリクエスト
    prompt = f"""{system_prompt}

【直近の会話】
{conversation_context}

【現在のユーザーメッセージ】
{user_message}

【あなたの応答】"""

    try:
        response = model.generate_content(prompt)
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

    # ポストバックデータをパース
    params = dict(param.split('=') for param in postback_data.split('&'))
    action = params.get('action', '')

    reply_text = f"ポストバックを受け取りました: {action}"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )
