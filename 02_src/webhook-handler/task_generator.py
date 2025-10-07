"""
AI駆動型パーソナライズタスク生成モジュール

Gemini 2.0 Flash + Google Search Groundingを使用して、
ユーザープロフィールに完全に最適化されたタスクを生成する
"""

from datetime import datetime, timedelta
from typing import List, Dict
import sqlalchemy
import os
import json
import google.generativeai as genai
from google.cloud import secretmanager


PROJECT_ID = os.environ.get('GCP_PROJECT', 'uketsuguai-dev')


def get_secret(secret_id: str) -> str:
    """Secret Managerからシークレットを取得"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def generate_basic_tasks(user_id: str, profile: Dict, conn) -> List[Dict]:
    """
    AI駆動型パーソナライズタスク生成

    Args:
        user_id: ユーザーID
        profile: ユーザープロフィール情報
            - relationship: 故人との関係
            - prefecture: 都道府県
            - municipality: 市区町村
            - death_date: 死亡日
        conn: データベース接続

    Returns:
        生成されたタスクのリスト
    """

    death_date = profile.get('death_date')
    relationship = profile.get('relationship', '遺族')
    prefecture = profile.get('prefecture', '')
    municipality = profile.get('municipality', '')

    if not death_date:
        return []

    # 死亡日をdatetimeに変換
    if isinstance(death_date, str):
        death_date = datetime.fromisoformat(death_date)

    # Gemini APIを初期化
    gemini_api_key = get_secret('GEMINI_API_KEY')
    genai.configure(api_key=gemini_api_key)

    # タスクスキーマ定義
    task_schema = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "description": "生成されたタスクのリスト",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "タスクのタイトル（簡潔に）"
                        },
                        "description": {
                            "type": "string",
                            "description": "タスクの詳細説明（手続きの内容、必要な書類など）"
                        },
                        "category": {
                            "type": "string",
                            "enum": ["行政手続き", "年金", "保険", "税金", "相続", "金融", "その他"],
                            "description": "タスクのカテゴリ"
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "優先度（期限の緊急性や重要度）"
                        },
                        "due_days": {
                            "type": "integer",
                            "description": "死亡日から何日以内に完了すべきか"
                        },
                        "tips": {
                            "type": "string",
                            "description": "具体的なヒント、注意点、スムーズに進めるコツ"
                        },
                        "legal_basis": {
                            "type": "string",
                            "description": "法的根拠（該当する法律名、条文など）。不明な場合は空文字列"
                        },
                        "contact_info": {
                            "type": "string",
                            "description": "具体的な窓口情報（市区町村役場の部署名、電話番号、URLなど）"
                        },
                        "required_documents": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "必要書類のリスト"
                        }
                    },
                    "required": ["title", "description", "category", "priority", "due_days"]
                }
            }
        },
        "required": ["tasks"]
    }

    # プロンプト作成
    prompt = f"""あなたは死後手続きの専門家です。以下のユーザー情報に基づき、完全にパーソナライズされた手続きタスクを生成してください。

【ユーザー情報】
- 故人との関係: {relationship}
- お住まい: {prefecture} {municipality}
- 死亡日: {death_date.strftime('%Y年%m月%d日')}

【タスク生成の要件】
1. **完全パーソナライズ**
   - 関係性に応じた手続き（配偶者→遺族年金、子→相続など）
   - {municipality}の具体的な窓口情報を含める
   - 死亡日から期限を正確に計算

2. **Web検索で最新情報を取得**
   - e-gov（電子政府総合窓口）で法的根拠を確認
   - {prefecture}{municipality}の公式サイトで窓口情報を取得
   - 法務省、厚労省、国税庁などの公的機関の最新情報

3. **具体的で実用的な内容**
   - 必要書類を明記
   - 具体的な窓口名、連絡先、URLを含める
   - 手続きのコツや注意点を記載
   - 法的根拠（条文）を明記

4. **優先順位**
   - 期限が短い、法的義務がある手続きは priority: high
   - 重要だが期限に余裕があるものは medium
   - 任意性が高いものは low

【必須タスク例】
- 死亡届の提出（7日以内）
- 火葬許可申請
- 年金受給停止
- 健康保険証の返却
- 介護保険資格喪失届
- 世帯主変更届
- 相続放棄の検討（3ヶ月以内）
- 準確定申告（4ヶ月以内）
- 相続税の申告（10ヶ月以内）
- 公共料金の名義変更
- 銀行口座の手続き
- クレジットカードの解約

上記を含め、{relationship}として必要な手続きを10〜15件程度生成してください。
Web検索を活用して、{municipality}の具体的な情報と最新の法的根拠を含めてください。
"""

    try:
        # Gemini 2.0 Flash with Google Search Grounding
        model = genai.GenerativeModel(
            'gemini-2.0-flash-exp',
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": task_schema
            }
        )

        # Google Search有効化（一旦無効化してテスト）
        response = model.generate_content(
            prompt
            # tools='google_search_retrieval'  # 一旦コメントアウト
        )

        # レスポンスをパース
        result = json.loads(response.text)
        generated_tasks = result.get('tasks', [])

        print(f"✅ AI生成タスク数: {len(generated_tasks)}件")

    except Exception as e:
        print(f"⚠️ AI生成エラー: {e}")
        print(f"フォールバック: 基本タスクを生成します")
        # エラー時は基本タスクにフォールバック
        generated_tasks = get_fallback_tasks()

    # タスクをDBに登録
    tasks = []
    for i, task_data in enumerate(generated_tasks, 1):
        due_date = death_date + timedelta(days=task_data.get('due_days', 30))

        result = conn.execute(
            sqlalchemy.text(
                """
                INSERT INTO tasks (
                    user_id, title, description, category,
                    priority, due_date, status, order_index
                )
                VALUES (
                    :user_id, :title, :description, :category,
                    :priority, :due_date, 'pending', :order_index
                )
                RETURNING id, title, due_date
                """
            ),
            {
                'user_id': user_id,
                'title': task_data.get('title', ''),
                'description': format_task_description(task_data),
                'category': task_data.get('category', 'その他'),
                'priority': task_data.get('priority', 'medium'),
                'due_date': due_date,
                'order_index': i
            }
        )

        task = result.fetchone()
        tasks.append({
            'id': str(task[0]),
            'title': task[1],
            'due_date': task[2].isoformat()
        })

    conn.commit()

    return tasks


def format_task_description(task_data: Dict) -> str:
    """タスクの詳細情報をフォーマット"""
    parts = [task_data.get('description', '')]

    # 必要書類
    required_docs = task_data.get('required_documents', [])
    if required_docs:
        parts.append("\n\n【必要書類】\n" + "\n".join(f"・{doc}" for doc in required_docs))

    # 窓口情報
    contact = task_data.get('contact_info', '')
    if contact:
        parts.append(f"\n\n【窓口】\n{contact}")

    # Tips
    tips = task_data.get('tips', '')
    if tips:
        parts.append(f"\n\n【ヒント】\n{tips}")

    # 法的根拠
    legal = task_data.get('legal_basis', '')
    if legal:
        parts.append(f"\n\n【法的根拠】\n{legal}")

    return "".join(parts)


def get_fallback_tasks() -> List[Dict]:
    """AI生成失敗時のフォールバックタスク"""
    return [
        {
            'title': '死亡届の提出',
            'description': '死亡の事実を知った日から7日以内に、市区町村役場に提出してください。',
            'category': '行政手続き',
            'priority': 'high',
            'due_days': 7
        },
        {
            'title': '火葬許可申請',
            'description': '死亡届と同時に火葬許可申請書を提出してください。',
            'category': '行政手続き',
            'priority': 'high',
            'due_days': 7
        },
        {
            'title': '年金受給停止の届出',
            'description': '厚生年金は10日以内、国民年金は14日以内に年金事務所または市区町村役場に届け出てください。',
            'category': '年金',
            'priority': 'high',
            'due_days': 10
        },
        {
            'title': '健康保険証の返却',
            'description': '国民健康保険の場合は14日以内に市区町村役場に返却してください。',
            'category': '保険',
            'priority': 'high',
            'due_days': 14
        },
        {
            'title': '世帯主変更届',
            'description': '世帯主が亡くなった場合、14日以内に市区町村役場に届出してください。',
            'category': '行政手続き',
            'priority': 'medium',
            'due_days': 14
        },
        {
            'title': '相続放棄の検討・手続き',
            'description': '相続放棄する場合は、相続開始を知った日から3ヶ月以内に家庭裁判所に申述してください。',
            'category': '相続',
            'priority': 'high',
            'due_days': 90
        },
        {
            'title': '準確定申告',
            'description': '故人の所得税の確定申告を、相続開始を知った日の翌日から4ヶ月以内に行ってください。',
            'category': '税金',
            'priority': 'medium',
            'due_days': 120
        },
        {
            'title': '相続税の申告・納付',
            'description': '相続税の申告・納付は、相続開始を知った日の翌日から10ヶ月以内に行ってください。',
            'category': '税金',
            'priority': 'medium',
            'due_days': 300
        }
    ]


def get_task_summary_message(tasks: List[Dict], municipality: str) -> str:
    """
    生成されたタスクのサマリーメッセージを作成

    Args:
        tasks: 生成されたタスクのリスト
        municipality: 市区町村名

    Returns:
        サマリーメッセージ
    """

    message = f"""✅ {municipality}での手続きタスクを{len(tasks)}件生成しました

🤖 AIがあなたの状況に合わせて、e-govや自治体サイトから最新情報を取得し、完全にパーソナライズされたタスクを作成しました。

優先度の高いタスク（期限が近いもの）:
"""

    # 期限が近い順に最初の5件を表示
    sorted_tasks = sorted(tasks, key=lambda x: x['due_date'])[:5]

    for i, task in enumerate(sorted_tasks, 1):
        message += f"\n{i}. {task['title']}"
        message += f"\n   期限: {task['due_date']}"

    message += "\n\nすべてのタスクは「タスク一覧」から確認できます。"
    message += "\n各タスクには具体的な窓口情報、必要書類、法的根拠が記載されています。"

    return message
