"""
簡易タスク生成モジュール

ユーザープロフィール情報を基に、基本的な死後手続きタスクを生成する
"""

from datetime import datetime, timedelta
from typing import List, Dict
import sqlalchemy


def generate_basic_tasks(user_id: str, profile: Dict, conn) -> List[Dict]:
    """
    基本的な死後手続きタスクを生成

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
    if not death_date:
        return []

    # 死亡日をdatetimeに変換
    if isinstance(death_date, str):
        death_date = datetime.fromisoformat(death_date)

    tasks = []

    # 基本的なタスクテンプレート
    task_templates = [
        {
            'title': '死亡届の提出',
            'description': '死亡の事実を知った日から7日以内に、市区町村役場に提出してください。',
            'category': '行政手続き',
            'priority': 'high',
            'due_days': 7,
            'order_index': 1
        },
        {
            'title': '火葬許可申請',
            'description': '死亡届と同時に火葬許可申請書を提出してください。',
            'category': '行政手続き',
            'priority': 'high',
            'due_days': 7,
            'order_index': 2
        },
        {
            'title': '年金受給停止の届出',
            'description': '厚生年金は10日以内、国民年金は14日以内に年金事務所または市区町村役場に届け出てください。',
            'category': '年金',
            'priority': 'high',
            'due_days': 10,
            'order_index': 3
        },
        {
            'title': '健康保険証の返却',
            'description': '国民健康保険の場合は14日以内に市区町村役場に返却してください。',
            'category': '保険',
            'priority': 'high',
            'due_days': 14,
            'order_index': 4
        },
        {
            'title': '介護保険資格喪失届',
            'description': '65歳以上または40〜64歳で要介護認定を受けていた場合、14日以内に届出が必要です。',
            'category': '保険',
            'priority': 'medium',
            'due_days': 14,
            'order_index': 5
        },
        {
            'title': '世帯主変更届',
            'description': '世帯主が亡くなった場合、14日以内に市区町村役場に届出してください。',
            'category': '行政手続き',
            'priority': 'medium',
            'due_days': 14,
            'order_index': 6
        },
        {
            'title': '相続放棄の検討・手続き',
            'description': '相続放棄する場合は、相続開始を知った日から3ヶ月以内に家庭裁判所に申述してください。',
            'category': '相続',
            'priority': 'high',
            'due_days': 90,
            'order_index': 7
        },
        {
            'title': '準確定申告',
            'description': '故人の所得税の確定申告を、相続開始を知った日の翌日から4ヶ月以内に行ってください。',
            'category': '税金',
            'priority': 'medium',
            'due_days': 120,
            'order_index': 8
        },
        {
            'title': '相続税の申告・納付',
            'description': '相続税の申告・納付は、相続開始を知った日の翌日から10ヶ月以内に行ってください。',
            'category': '税金',
            'priority': 'medium',
            'due_days': 300,
            'order_index': 9
        },
        {
            'title': '公共料金の名義変更・解約',
            'description': '電気・ガス・水道・電話などの名義変更または解約手続きを行ってください。',
            'category': 'その他',
            'priority': 'medium',
            'due_days': 30,
            'order_index': 10
        },
        {
            'title': '銀行口座の凍結解除・名義変更',
            'description': '金融機関に連絡し、必要な手続きを確認してください。',
            'category': '金融',
            'priority': 'medium',
            'due_days': 60,
            'order_index': 11
        },
        {
            'title': 'クレジットカードの解約',
            'description': '各クレジットカード会社に連絡し、解約手続きを行ってください。',
            'category': 'その他',
            'priority': 'low',
            'due_days': 30,
            'order_index': 12
        }
    ]

    # タスクをDBに登録
    for template in task_templates:
        due_date = death_date + timedelta(days=template['due_days'])

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
                'title': template['title'],
                'description': template['description'],
                'category': template['category'],
                'priority': template['priority'],
                'due_date': due_date,
                'order_index': template['order_index']
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

優先度の高いタスク（期限が近いもの）:
"""

    # 期限が近い順に最初の5件を表示
    sorted_tasks = sorted(tasks, key=lambda x: x['due_date'])[:5]

    for i, task in enumerate(sorted_tasks, 1):
        message += f"\n{i}. {task['title']}"
        message += f"\n   期限: {task['due_date']}"

    message += "\n\nすべてのタスクは「タスク一覧」から確認できます。"

    return message
