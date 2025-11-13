"""
AIチャットサービスモジュール
Gemini APIを使用したAI応答生成と会話履歴管理
"""
import sqlalchemy
from sqlalchemy import text
from core.db import get_db_engine, get_gemini_client
from knowledge_base import search_knowledge


def generate_ai_response(user_id: str, user_message: str) -> str:
    """
    Gemini APIを使ってAI応答を生成

    Args:
        user_id: ユーザーID
        user_message: ユーザーのメッセージ

    Returns:
        AI応答テキスト
    """
    engine = get_db_engine()
    client = get_gemini_client()

    # ユーザープロフィールとタスク情報を取得
    with engine.connect() as conn:
        profile_data = conn.execute(
            text(
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
            text(
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
        # Gemini 2.5 Proで応答生成
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt
        )
        ai_reply = response.text

        # アシスタントの応答を会話履歴に保存
        with engine.connect() as conn:
            conn.execute(
                text(
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


def save_user_message(user_id: str, message: str) -> None:
    """
    ユーザーメッセージを会話履歴に保存

    Args:
        user_id: ユーザーID
        message: ユーザーのメッセージ
    """
    engine = get_db_engine()

    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO conversation_history (user_id, role, message)
                VALUES (:user_id, 'user', :message)
                """
            ),
            {
                "user_id": user_id,
                "message": message
            }
        )
        conn.commit()
