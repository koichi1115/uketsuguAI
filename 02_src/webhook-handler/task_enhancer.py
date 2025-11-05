"""
タスク拡張モジュール

SNS・ブログから実用的なTips・体験談を収集し、
既存タスクに追記または新規タスクとして追加する（Step 3: Enhanced）
"""

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


def enhance_tasks_with_tips(user_id: str, conn) -> Dict[str, int]:
    """
    既存タスクにSNS・ブログから収集したTipsを追加

    Args:
        user_id: ユーザーID
        conn: データベース接続

    Returns:
        統計情報 {'enhanced_count': X, 'new_tips_count': Y}
    """

    # Gemini APIクライアントを初期化
    gemini_api_key = get_secret('GEMINI_API_KEY')
    client = genai.Client(api_key=gemini_api_key)

    # ユーザーの既存タスクを取得
    tasks = _get_user_tasks(user_id, conn)

    if not tasks:
        return {'enhanced_count': 0, 'new_tips_count': 0}

    try:
        print("🔍 Tips収集開始（Step 3: Enhanced）...")

        # タスクリストをテキストに変換
        tasks_summary = "\n".join([f"- {task['title']}" for task in tasks])

        # Tips収集プロンプト
        prompt = f"""以下は、ユーザーが死後手続きで実施する必要があるタスクのリストです。

【タスクリスト】
{tasks_summary}

【あなたの役割】
X（旧Twitter）、ブログ、口コミサイトから、これらの手続きに関する**リアルな体験談**を検索し、実用的なTipsを収集してください。

【収集すべき情報】

1. **時短テクニック**
   - 「このタイミングでやっておくと楽」
   - 「事前にコピーしておくべき書類」
   - 「電話で事前確認すべきこと」
   - 「午前中に行くと空いている」

2. **お得情報**
   - 「補助金・給付金がもらえる」
   - 「手数料が戻ってくる」
   - 「減税措置がある」
   - 「知らないと損する制度」

3. **注意喚起・後悔談**
   - 「これをやっておけば良かった」
   - 「知らずに損した」
   - 「窓口で断られた理由」
   - 「二度手間になったケース」

4. **実用的なチェックリスト**
   - 「窓口に持っていくべきもの」
   - 「準備しておくと便利なもの」
   - 「印鑑は実印が必要」

5. **感情的なサポート**
   - 「同じ経験をした人の励まし」
   - 「乗り越え方のアドバイス」

【検索キーワード例】
- 「死後手続き やっておくと楽」
- 「死亡届 知らないと損」
- 「遺族年金 申請 コツ」
- 「相続手続き 後悔」
- 「年金停止 注意点」

各タスクに対して、実用的で具体的なTipsを収集してください。
公式情報ではなく、**個人の体験に基づくリアルな情報**を優先してください。
"""

        # Google Search Groundingでリアルな体験談を収集
        tips_response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )

        collected_tips = tips_response.text
        print(f"✅ Tips収集完了: {len(collected_tips)}文字")

        # 収集したTipsを各タスクに振り分ける
        distribution_prompt = f"""以下は、SNS・ブログから収集した死後手続きに関する実用的なTipsです。

【収集したTips】
{collected_tips}

【タスクリスト】
{tasks_summary}

これらのTipsを、各タスクに振り分けてください。
各タスクに対して、そのタスクに関連する具体的で実用的なTipsを抽出してください。

JSON形式で以下のように出力してください：
{{
  "task_tips": [
    {{
      "task_title": "タスクのタイトル",
      "tips": "このタスクに関する実用的なTips（複数ある場合は改行で区切る）"
    }}
  ]
}}
"""

        tips_schema = {
            "type": "object",
            "properties": {
                "task_tips": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task_title": {"type": "string"},
                            "tips": {"type": "string"}
                        },
                        "required": ["task_title", "tips"]
                    }
                }
            },
            "required": ["task_tips"]
        }

        distribution_response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=distribution_prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=tips_schema
            )
        )

        result = json.loads(distribution_response.text)
        task_tips_list = result.get('task_tips', [])

        print(f"✅ Tips振り分け完了: {len(task_tips_list)}件")

    except Exception as e:
        print(f"⚠️ Tips収集エラー: {e}")
        return {'enhanced_count': 0, 'new_tips_count': 0}

    # 各タスクにTipsを追加
    enhanced_count = 0
    new_tips_count = 0

    for task_tips in task_tips_list:
        task_title = task_tips.get('task_title', '')
        tips = task_tips.get('tips', '')

        if not tips:
            continue

        # タスクを検索
        matching_task = None
        for task in tasks:
            if task_title in task['title'] or task['title'] in task_title:
                matching_task = task
                break

        if matching_task:
            # 既存タスクのtipsフィールドを更新
            existing_tips = matching_task.get('tips', '')

            if existing_tips:
                updated_tips = f"{existing_tips}\n\n【体験談・口コミ】\n{tips}"
            else:
                updated_tips = f"【体験談・口コミ】\n{tips}"

            conn.execute(
                sqlalchemy.text(
                    """
                    UPDATE tasks
                    SET tips = :tips, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :task_id
                    """
                ),
                {'tips': updated_tips, 'task_id': matching_task['id']}
            )

            enhanced_count += 1
            new_tips_count += tips.count('\n') + 1

    conn.commit()

    print(f"✅ タスク拡張完了: {enhanced_count}件のタスクに{new_tips_count}個のTipsを追加")

    return {
        'enhanced_count': enhanced_count,
        'new_tips_count': new_tips_count
    }


def _get_user_tasks(user_id: str, conn) -> List[Dict]:
    """ユーザーのタスクを取得"""

    result = conn.execute(
        sqlalchemy.text(
            """
            SELECT id, title, description, category, tips
            FROM tasks
            WHERE user_id = :user_id AND is_deleted = false
            ORDER BY order_index
            """
        ),
        {'user_id': user_id}
    )

    tasks = []
    for row in result:
        tasks.append({
            'id': str(row[0]),
            'title': row[1],
            'description': row[2],
            'category': row[3],
            'tips': row[4] or ''
        })

    return tasks


def generate_general_tips_task(user_id: str, basic_profile: Dict, conn) -> bool:
    """
    全体的なお得情報・注意点をまとめた「知っておくべきこと」タスクを生成

    Args:
        user_id: ユーザーID
        basic_profile: 基本プロフィール情報
        conn: データベース接続

    Returns:
        成功した場合True
    """

    try:
        # Gemini APIクライアントを初期化
        gemini_api_key = get_secret('GEMINI_API_KEY')
        client = genai.Client(api_key=gemini_api_key)

        # プライバシー保護：AIに送信する情報を匿名化
        print("🔒 プライバシー保護: プロファイル情報を匿名化中...")
        anonymized_profile = anonymize_profile_for_ai(basic_profile)
        generalized_relationship = anonymized_profile.get('relationship', '遺族')

        prompt = f"""あなたは死後手続きの専門家です。{generalized_relationship}として知っておくべき、全体的なお得情報や注意点を収集してください。

【収集すべき情報】
1. 多くの人が知らない給付金・補助金
2. 申請しないともらえないお金
3. 手続きの順序で気をつけること
4. 「先にこれをやっておくべきだった」という後悔談
5. 窓口で教えてもらえないお得情報

SNS・ブログから、{generalized_relationship}向けの実用的な情報を収集してください。
"""

        tips_response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )

        general_tips = tips_response.text

        # 「知っておくべきこと」タスクとして保存
        conn.execute(
            sqlalchemy.text(
                """
                INSERT INTO tasks (
                    user_id, title, description, category,
                    priority, status, order_index, generation_step, tips
                )
                VALUES (
                    :user_id, :title, :description, :category,
                    :priority, 'pending', 0, 'enhanced', :tips
                )
                """
            ),
            {
                'user_id': user_id,
                'title': '💡 死後手続きで知っておくべきこと',
                'description': 'お得情報、注意点、後悔しないためのポイントをまとめました。',
                'category': 'その他',
                'priority': 'high',
                'tips': general_tips
            }
        )

        conn.commit()

        return True

    except Exception as e:
        print(f"⚠️ 全体Tipsタスク生成エラー: {e}")
        return False
