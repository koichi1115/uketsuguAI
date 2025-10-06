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
import sqlalchemy
from datetime import datetime, timezone
import google.generativeai as genai
from flex_messages import create_task_list_flex, create_task_completed_flex
from knowledge_base import search_knowledge

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
        user_id, user_message, relationship, prefecture, municipality, death_date
    )

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 返信メッセージの種類を判定
        if isinstance(reply_message, dict):
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
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text="タスク一覧", contents=FlexContainer.from_dict(reply_message))]
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


def process_profile_collection(user_id, message, relationship, prefecture, municipality, death_date):
    """プロフィール収集処理"""
    from task_generator import generate_basic_tasks, get_task_summary_message

    engine = get_db_engine()

    # ヘルプと設定は常に表示可能
    if message == 'ヘルプ':
        return get_help_message()
    elif message == '設定':
        return get_settings_message(user_id, relationship, prefecture, municipality, death_date)

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
                elif message == 'ヘルプ':
                    return get_help_message()
                elif message == '設定':
                    return get_settings_message(user_id, relationship, prefecture, municipality, death_date)
                elif '完了' in message and any(c.isdigit() or c in '０１２３４５６７８９' for c in message):
                    # 「完了1」「1完了」「完了１」「１完了」などのパターンをチェック
                    return complete_task(user_id, message)
                else:
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


def get_task_list_message(user_id: str, show_all: bool = False):
    """タスク一覧をFlex Messageで返す"""
    engine = get_db_engine()

    with engine.connect() as conn:
        tasks = conn.execute(
            sqlalchemy.text(
                """
                SELECT id, title, due_date, status, priority, category
                FROM tasks
                WHERE user_id = :user_id AND is_deleted = false
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

    # Flex Messageを返す
    return create_task_list_flex(tasks, show_all=show_all)


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
                WHERE id = :task_id
                """
            ),
            {"task_id": task_id}
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
- 「心よりお悔やみ申し上げます」などの前置きは不要
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
        # TODO: Google Search Groundingは後で実装
        # 現在のgoogle-generativeaiパッケージがGemini 2.0のgoogle_searchに未対応
        # 代替案: プロンプトで最新情報の参照を促す
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
    engine = get_db_engine()

    # ポストバックデータをパース
    params = dict(param.split('=') for param in postback_data.split('&'))
    action = params.get('action', '')

    if action == 'complete_task':
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
                            WHERE id = :task_id
                            """
                        ),
                        {"task_id": task_id}
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
                            WHERE id = :task_id
                            """
                        ),
                        {"task_id": task_id}
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
        from task_generator import generate_basic_tasks, get_task_summary_message

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

                # タスク生成
                tasks = generate_basic_tasks(
                    user_id,
                    {
                        'death_date': death_dt,
                        'prefecture': prefecture,
                        'municipality': municipality
                    },
                    conn
                )

                reply_message = get_task_summary_message(tasks, municipality)

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
k.shimada1115@gmail.com

💡 **ヒント**
- 「タスク」でタスク一覧を表示
- 「全タスク」で完了済み含む全て表示
- 質問は自由に入力してください"""


def get_settings_message(user_id: str, relationship: str, prefecture: str, municipality: str, death_date) -> str:
    """設定メッセージを生成"""
    # 死亡日をフォーマット
    death_date_str = death_date.strftime("%Y年%m月%d日") if death_date else "未設定"

    return f"""【現在の設定】

👤 **故人との関係**: {relationship or '未設定'}
📍 **お住まい**: {prefecture or '未設定'} {municipality or ''}
📅 **死亡日**: {death_date_str}

💡 プロフィール情報を変更したい場合は、お手数ですが管理者までお問い合わせください。
📧 k.shimada1115@gmail.com"""
