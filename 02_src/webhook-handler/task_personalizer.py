"""
個別タスク生成モジュール

追加質問の回答に基づいて、ユーザー固有の状況に特化した
タスクを生成する（Step 2: Personalized）
"""

from datetime import datetime, timedelta
from typing import List, Dict
import sqlalchemy
import os
import json
from google import genai
from google.genai import types
from google.cloud import secretmanager
from privacy_utils import anonymize_profile_for_ai


PROJECT_ID = os.environ.get('GCP_PROJECT', 'uketsuguai-dev')


def get_secret(secret_id: str) -> str:
    """Secret Managerからシークレットを取得"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def generate_personalized_tasks(
    user_id: str,
    basic_profile: Dict,
    additional_answers: Dict,
    conn
) -> List[Dict]:
    """
    追加質問の回答に基づいて個別タスクを生成

    Args:
        user_id: ユーザーID
        basic_profile: 基本プロフィール情報
        additional_answers: 追加質問の回答 {question_key: answer}
        conn: データベース接続

    Returns:
        生成されたタスクのリスト
    """

    death_date = basic_profile.get('death_date')
    relationship = basic_profile.get('relationship', '遺族')
    prefecture = basic_profile.get('prefecture', '')
    municipality = basic_profile.get('municipality', '')

    if not death_date:
        return []

    # 死亡日をdatetimeに変換
    if isinstance(death_date, str):
        death_date = datetime.fromisoformat(death_date)

    # プライバシー保護：AIに送信する情報を匿名化
    print("🔒 プライバシー保護: プロファイル情報を匿名化中...")
    anonymized_profile = anonymize_profile_for_ai(basic_profile)

    # Gemini APIクライアントを初期化
    gemini_api_key = get_secret('GEMINI_API_KEY')
    client = genai.Client(api_key=gemini_api_key)

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
                            "description": "タスクの詳細説明"
                        },
                        "category": {
                            "type": "string",
                            "enum": ["行政手続き", "年金", "保険", "税金", "相続", "金融", "その他"],
                            "description": "タスクのカテゴリ"
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "優先度"
                        },
                        "due_days": {
                            "type": "integer",
                            "description": "死亡日から何日以内に完了すべきか"
                        },
                        "tips": {
                            "type": "string",
                            "description": "具体的なヒント、注意点"
                        },
                        "legal_basis": {
                            "type": "string",
                            "description": "法的根拠"
                        },
                        "contact_info": {
                            "type": "string",
                            "description": "窓口情報"
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

    # 追加質問の回答をテキストに変換
    answers_text = _format_answers_for_prompt(additional_answers)

    try:
        print("🔍 個別タスク生成中（Step 2: Personalized）...")

        # プロンプト作成
        prompt = f"""あなたは死後手続きの専門家です。以下のユーザー情報に基づき、このユーザー固有の状況に特化したタスクを生成してください。

【基本情報】
- 故人との関係: {relationship}
- お住まい: {prefecture} {municipality}
- 死亡日: {death_date.strftime('%Y年%m月%d日')}

【追加情報（ユーザーからの回答）】
{answers_text}

【タスク生成の要件】

1. **完全にパーソナライズされたタスクのみ生成**
   - 上記の追加情報に基づき、このユーザーに**必要なタスクのみ**を生成
   - 例: has_real_estate = はい → 不動産相続登記を生成
   - 例: has_vehicle = いいえ → 車両関連タスクは生成しない

2. **Google検索で最新の情報を取得**
   - 各手続きの具体的な窓口情報を{prefecture}{municipality}で検索
   - 必要書類、手続きの流れを検索
   - 手数料、期限などの最新情報を検索

3. **生成すべきタスクの例**
   - 年金受給中 → 遺族年金申請、未支給年金請求
   - 介護サービス利用中 → 介護保険資格喪失届、介護保険料返還請求
   - 不動産保有 → 相続登記、固定資産税納税義務者変更
   - 車両保有 → 自動車名義変更、自動車保険変更
   - 生命保険加入 → 生命保険金請求
   - 自営業 → 個人事業廃業届、消費税申告
   - 扶養家族あり → 健康保険の扶養変更、児童手当受給者変更
   - 子供あり → 遺族年金（子の加算）申請

4. **具体的な内容**
   - 必要書類を明記
   - {prefecture}{municipality}の具体的な窓口情報
   - 手続きのコツや注意点

5〜10件程度のタスクを生成してください。
"""

        # 第1段階: Google Search Groundingで情報収集
        grounding_response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )

        collected_info = grounding_response.text
        print(f"✅ 情報収集完了: {len(collected_info)}文字")

        # 第2段階: JSON形式で構造化
        structuring_prompt = f"""以下は、Google検索で収集したユーザー固有の手続き情報です。
この情報をもとに、JSON形式でタスクリストを生成してください。

【収集した情報】
{collected_info}

【重要】
- ユーザーに関係のないタスクは含めない
- 5〜10件程度のタスクを生成
- 各タスクは具体的で実用的な内容にする
"""

        structuring_response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=structuring_prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=task_schema
            )
        )

        # レスポンスをパース
        result = json.loads(structuring_response.text)
        generated_tasks = result.get('tasks', [])

        print(f"✅ 個別タスク生成完了: {len(generated_tasks)}件")

    except Exception as e:
        print(f"⚠️ 個別タスク生成エラー: {e}")
        generated_tasks = []

    # タスクをDBに登録
    tasks = []

    # 既存タスクの最大order_indexを取得
    max_order = conn.execute(
        sqlalchemy.text(
            "SELECT COALESCE(MAX(order_index), 0) FROM tasks WHERE user_id = :user_id"
        ),
        {'user_id': user_id}
    ).fetchone()[0]

    for i, task_data in enumerate(generated_tasks, 1):
        due_date = death_date + timedelta(days=task_data.get('due_days', 30))

        result = conn.execute(
            sqlalchemy.text(
                """
                INSERT INTO tasks (
                    user_id, title, description, category,
                    priority, due_date, status, order_index, generation_step, tips
                )
                VALUES (
                    :user_id, :title, :description, :category,
                    :priority, :due_date, 'pending', :order_index, 'personalized', :tips
                )
                RETURNING id, title, due_date
                """
            ),
            {
                'user_id': user_id,
                'title': task_data.get('title', ''),
                'description': _format_task_description(task_data),
                'category': task_data.get('category', 'その他'),
                'priority': task_data.get('priority', 'medium'),
                'due_date': due_date,
                'order_index': max_order + i,
                'tips': task_data.get('tips', '')
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


def _format_answers_for_prompt(answers: Dict[str, str]) -> str:
    """追加質問の回答をプロンプト用にフォーマット"""

    lines = []

    question_labels = {
        'has_pension': '年金受給',
        'has_care_insurance': '介護保険サービス利用',
        'has_real_estate': '不動産保有',
        'has_vehicle': '車両保有',
        'has_life_insurance': '生命保険加入',
        'is_self_employed': '自営業',
        'is_dependent_family': '扶養家族',
        'has_children': '子供'
    }

    for key, answer in answers.items():
        label = question_labels.get(key, key)
        lines.append(f"- {label}: {answer}")

    return "\n".join(lines)


def _format_task_description(task_data: Dict) -> str:
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

    # 法的根拠
    legal = task_data.get('legal_basis', '')
    if legal:
        parts.append(f"\n\n【法的根拠】\n{legal}")

    return "".join(parts)
