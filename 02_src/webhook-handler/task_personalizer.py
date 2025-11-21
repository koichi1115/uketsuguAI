"""
個別タスク生成モジュール

追加質問の回答に基づいて、ユーザー固有の状況に特化した
タスクを生成する（Step 2: Personalized）

Enhanced: 具体的なサービス名（保険会社・銀行等）ごとに個別タスクを生成
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
from service_providers import (
    get_search_keyword,
    get_task_title,
    SERVICE_CATEGORIES,
)


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


def generate_service_specific_tasks(
    user_id: str,
    basic_profile: Dict,
    selected_services: Dict[str, List[str]],
    conn
) -> List[Dict]:
    """
    選択されたサービスごとに個別タスクを生成

    Args:
        user_id: ユーザーID
        basic_profile: 基本プロフィール情報
        selected_services: {service_type: [service_name, ...]}
        conn: データベース接続

    Returns:
        生成されたタスクのリスト
    """
    death_date = basic_profile.get('death_date')
    if not death_date:
        return []

    if isinstance(death_date, str):
        death_date = datetime.fromisoformat(death_date)

    # Gemini APIクライアントを初期化
    gemini_api_key = get_secret('GEMINI_API_KEY')
    client = genai.Client(api_key=gemini_api_key)

    all_tasks = []

    # 既存タスクの最大order_indexを取得
    max_order = conn.execute(
        sqlalchemy.text(
            "SELECT COALESCE(MAX(order_index), 0) FROM tasks WHERE user_id = :user_id"
        ),
        {'user_id': user_id}
    ).fetchone()[0]

    task_index = 1

    for service_type, service_names in selected_services.items():
        category_info = SERVICE_CATEGORIES.get(service_type, {})

        for service_name in service_names:
            if service_name in ['その他', '選択完了', '該当なし']:
                continue

            print(f"🔍 {service_name}の手続き情報を検索中...")

            try:
                task_data = _generate_single_service_task(
                    client, service_type, service_name, basic_profile
                )

                if task_data:
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
                                :priority, :due_date, 'pending', :order_index, 'service_specific', :tips
                            )
                            RETURNING id, title, due_date
                            """
                        ),
                        {
                            'user_id': user_id,
                            'title': task_data.get('title', f'{service_name}の手続き'),
                            'description': _format_task_description(task_data),
                            'category': task_data.get('category', category_info.get('label', 'その他')),
                            'priority': task_data.get('priority', 'medium'),
                            'due_date': due_date,
                            'order_index': max_order + task_index,
                            'tips': task_data.get('tips', '')
                        }
                    )

                    task = result.fetchone()
                    all_tasks.append({
                        'id': str(task[0]),
                        'title': task[1],
                        'due_date': task[2].isoformat(),
                        'service_name': service_name,
                        'service_type': service_type
                    })
                    task_index += 1
                    print(f"✅ {service_name}のタスク生成完了")

            except Exception as e:
                print(f"⚠️ {service_name}のタスク生成エラー: {e}")
                # エラー時もフォールバックタスクを生成
                fallback_task = _create_fallback_service_task(
                    user_id, service_type, service_name, death_date,
                    max_order + task_index, conn
                )
                if fallback_task:
                    all_tasks.append(fallback_task)
                    task_index += 1

    conn.commit()
    print(f"✅ サービス固有タスク生成完了: {len(all_tasks)}件")

    return all_tasks


def _generate_single_service_task(
    client,
    service_type: str,
    service_name: str,
    basic_profile: Dict
) -> Dict:
    """
    単一サービスのタスク情報をLLMで生成

    Args:
        client: Gemini APIクライアント
        service_type: サービス種別
        service_name: サービス名
        basic_profile: 基本プロフィール

    Returns:
        タスクデータ辞書
    """
    search_keyword = get_search_keyword(service_type, service_name)
    task_title = get_task_title(service_type, service_name)

    # サービスタイプ別のプロンプトテンプレート
    prompts_by_type = {
        'life_insurance': f"""
「{service_name}」の死亡保険金請求について、以下の情報を検索して取得してください：

1. 請求に必要な書類の完全なリスト
2. 請求の流れ・手順
3. コールセンターの電話番号と営業時間
4. オンライン手続きの可否
5. 請求期限（時効）
6. 支払いまでの目安日数
7. よくある注意点・トラブル事例
8. 「知っておくと得する」Tips（体験談ベース）

検索クエリ: {search_keyword}
""",
        'bank': f"""
「{service_name}」の相続手続き（口座凍結解除・名義変更・解約）について、以下の情報を検索して取得してください：

1. 必要書類の完全なリスト（残高による違いがあれば明記）
2. 手続きの流れ
3. 相続センターの電話番号
4. 手続き可能な窓口
5. 事前予約の要否
6. 手続き完了までの目安日数
7. 残高証明書の取得方法
8. 「知っておくと得する」Tips（体験談ベース）

検索クエリ: {search_keyword}
""",
        'credit_card': f"""
「{service_name}」の死亡時の解約手続きについて、以下の情報を検索して取得してください：

1. 解約に必要な書類
2. 連絡先電話番号
3. 未払い残高がある場合の処理
4. ポイント・マイルの扱い
5. 家族カードの扱い
6. 年会費の返金可否
7. 注意点・Tips

検索クエリ: {search_keyword}
""",
        'mobile_carrier': f"""
「{service_name}」の死亡時の解約・名義変更手続きについて、以下の情報を検索して取得してください：

1. 必要書類
2. 手続き方法（店舗/電話/オンライン）
3. 連絡先
4. 端末代金の残債がある場合の処理
5. 解約金・違約金の扱い
6. 電話番号の承継可否
7. 注意点・Tips

検索クエリ: {search_keyword}
""",
        'subscription': f"""
「{service_name}」の死亡時の解約手続きについて、以下の情報を検索して取得してください：

1. 解約方法
2. 必要な情報（アカウント情報など）
3. 連絡先・問い合わせ方法
4. 返金の可否
5. 共有アカウントの場合の扱い
6. 注意点

検索クエリ: {search_keyword}
""",
    }

    prompt = prompts_by_type.get(service_type, f"""
「{service_name}」の死亡時の手続きについて、以下の情報を検索して取得してください：
1. 必要書類
2. 手続き方法
3. 連絡先
4. 注意点・Tips

検索クエリ: {search_keyword}
""")

    # タスクスキーマ
    task_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "タスクのタイトル"},
            "description": {"type": "string", "description": "詳細説明"},
            "category": {
                "type": "string",
                "enum": ["行政手続き", "年金", "保険", "税金", "相続", "金融", "通信", "サブスクリプション", "その他"],
            },
            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
            "due_days": {"type": "integer", "description": "死亡日から何日以内"},
            "tips": {"type": "string", "description": "実用的なヒント"},
            "contact_info": {"type": "string", "description": "連絡先情報"},
            "required_documents": {
                "type": "array",
                "items": {"type": "string"},
                "description": "必要書類リスト"
            }
        },
        "required": ["title", "description", "category", "priority", "due_days"]
    }

    # Google Search Groundingで情報収集
    grounding_response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
    )

    collected_info = grounding_response.text

    # JSON形式で構造化
    structuring_prompt = f"""以下は「{service_name}」の手続きに関する検索結果です。
この情報をもとに、タスク情報をJSON形式で生成してください。

【タスクタイトル】
{task_title}

【収集した情報】
{collected_info}

【重要】
- titleは「{task_title}」を使用
- descriptionには手続きの流れを簡潔に記載
- tipsには「やっておくと楽」「知らないと損」などの実用的な情報を記載
- contact_infoには電話番号やURLを含める
- required_documentsには必要書類を漏れなくリスト化
"""

    structuring_response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=structuring_prompt,
        config=types.GenerateContentConfig(
            response_mime_type='application/json',
            response_schema=task_schema
        )
    )

    return json.loads(structuring_response.text)


def _create_fallback_service_task(
    user_id: str,
    service_type: str,
    service_name: str,
    death_date: datetime,
    order_index: int,
    conn
) -> Dict:
    """
    エラー時のフォールバックタスクを作成
    """
    task_title = get_task_title(service_type, service_name)
    category_info = SERVICE_CATEGORIES.get(service_type, {})

    # デフォルトの期限日数
    due_days_by_type = {
        'life_insurance': 90,
        'bank': 60,
        'credit_card': 30,
        'mobile_carrier': 14,
        'subscription': 14,
    }

    due_days = due_days_by_type.get(service_type, 30)
    due_date = death_date + timedelta(days=due_days)

    # 汎用的な説明文
    descriptions_by_type = {
        'life_insurance': f"{service_name}に連絡して、死亡保険金の請求手続きを行ってください。保険証券、死亡診断書、戸籍謄本等が必要です。",
        'bank': f"{service_name}に連絡して、口座の相続手続きを行ってください。残高証明書の取得も検討してください。",
        'credit_card': f"{service_name}に連絡して、カードの解約手続きを行ってください。未払い残高の確認も必要です。",
        'mobile_carrier': f"{service_name}に連絡して、契約の解約または名義変更手続きを行ってください。",
        'subscription': f"{service_name}の解約手続きを行ってください。アカウント情報が必要な場合があります。",
    }

    description = descriptions_by_type.get(service_type, f"{service_name}の手続きを行ってください。")

    result = conn.execute(
        sqlalchemy.text(
            """
            INSERT INTO tasks (
                user_id, title, description, category,
                priority, due_date, status, order_index, generation_step
            )
            VALUES (
                :user_id, :title, :description, :category,
                :priority, :due_date, 'pending', :order_index, 'service_specific'
            )
            RETURNING id, title, due_date
            """
        ),
        {
            'user_id': user_id,
            'title': task_title,
            'description': description,
            'category': category_info.get('label', 'その他'),
            'priority': 'medium',
            'due_date': due_date,
            'order_index': order_index
        }
    )

    task = result.fetchone()
    return {
        'id': str(task[0]),
        'title': task[1],
        'due_date': task[2].isoformat(),
        'service_name': service_name,
        'service_type': service_type
    }
