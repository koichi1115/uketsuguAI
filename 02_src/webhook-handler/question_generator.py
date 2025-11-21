"""
追加質問生成モジュール

基本タスク生成後に、ユーザーの詳細な状況を把握するための
追加質問を動的に生成する

Enhanced: 具体的なサービス名（保険会社・銀行等）の複数選択機能を追加
"""
import json
from typing import List, Dict, Optional
import sqlalchemy
from datetime import datetime, timedelta

from service_providers import (
    FOLLOW_UP_SERVICE_QUESTIONS,
    get_provider_names_for_quick_reply,
    SERVICE_CATEGORIES,
)


class FollowUpQuestion:
    """追加質問クラス"""

    def __init__(
        self,
        question_text: str,
        question_key: str,
        question_type: str = 'yes_no',
        options: Optional[List[str]] = None,
        display_order: int = 0
    ):
        self.question_text = question_text
        self.question_key = question_key
        self.question_type = question_type
        self.options = options or []
        self.display_order = display_order


def generate_follow_up_questions(
    user_id: str,
    basic_profile: Dict,
    basic_tasks: List[Dict],
    conn
) -> List[FollowUpQuestion]:
    """
    基本タスクに基づいて追加質問を生成

    Args:
        user_id: ユーザーID
        basic_profile: 基本プロフィール情報
        basic_tasks: 生成された基本タスクのリスト
        conn: データベース接続

    Returns:
        追加質問のリスト
    """

    relationship = basic_profile.get('relationship', '遺族')
    questions = []

    # 基本的な追加質問（すべてのユーザーに共通）
    base_questions = [
        FollowUpQuestion(
            question_text="故人は年金を受給していましたか？",
            question_key="has_pension",
            question_type="yes_no",
            display_order=1
        ),
        FollowUpQuestion(
            question_text="介護保険サービスを利用していましたか？",
            question_key="has_care_insurance",
            question_type="yes_no",
            display_order=2
        ),
        FollowUpQuestion(
            question_text="持ち家や土地などの不動産を保有していますか？",
            question_key="has_real_estate",
            question_type="yes_no",
            display_order=3
        ),
        FollowUpQuestion(
            question_text="車両（自動車・バイクなど）を保有していますか？",
            question_key="has_vehicle",
            question_type="yes_no",
            display_order=4
        ),
        FollowUpQuestion(
            question_text="生命保険に加入していましたか？",
            question_key="has_life_insurance",
            question_type="yes_no",
            display_order=5
        ),
        FollowUpQuestion(
            question_text="銀行口座を持っていましたか？",
            question_key="has_bank_account",
            question_type="yes_no",
            display_order=6
        ),
        FollowUpQuestion(
            question_text="クレジットカードを持っていましたか？",
            question_key="has_credit_card",
            question_type="yes_no",
            display_order=7
        ),
        FollowUpQuestion(
            question_text="携帯電話の契約はありましたか？",
            question_key="has_mobile_contract",
            question_type="yes_no",
            display_order=8
        ),
        FollowUpQuestion(
            question_text="サブスクリプションサービス（Netflix、Amazon Prime等）の契約はありましたか？",
            question_key="has_subscription",
            question_type="yes_no",
            display_order=9
        ),
        FollowUpQuestion(
            question_text="故人は自営業でしたか？",
            question_key="is_self_employed",
            question_type="yes_no",
            display_order=10
        ),
    ]

    questions.extend(base_questions)

    # 関係性に基づく追加質問
    if relationship in ['配偶者', '夫', '妻', '親']:
        questions.append(
            FollowUpQuestion(
                question_text="ご家族に扶養されていた方（お子様など）はいらっしゃいますか？",
                question_key="is_dependent_family",
                question_type="yes_no",
                display_order=11
            )
        )
        questions.append(
            FollowUpQuestion(
                question_text="お子様はいらっしゃいますか？",
                question_key="has_children",
                question_type="yes_no",
                display_order=12
            )
        )

    # データベースに質問を保存
    _save_questions_to_db(user_id, questions, conn)

    return questions


def _save_questions_to_db(user_id: str, questions: List[FollowUpQuestion], conn):
    """追加質問をデータベースに保存"""

    for question in questions:
        # 既に同じ質問が存在するか確認
        existing = conn.execute(
            sqlalchemy.text(
                """
                SELECT id FROM follow_up_questions
                WHERE user_id = :user_id AND question_key = :question_key
                """
            ),
            {'user_id': user_id, 'question_key': question.question_key}
        ).fetchone()

        if not existing:
            conn.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO follow_up_questions (
                        user_id, question_text, question_type, question_key,
                        options, display_order
                    )
                    VALUES (
                        :user_id, :question_text, :question_type, :question_key,
                        :options, :display_order
                    )
                    """
                ),
                {
                    'user_id': user_id,
                    'question_text': question.question_text,
                    'question_type': question.question_type,
                    'question_key': question.question_key,
                    'options': None if not question.options else json.dumps(question.options, ensure_ascii=False),
                    'display_order': question.display_order
                }
            )

    conn.commit()


def get_unanswered_questions(user_id: str, conn) -> List[Dict]:
    """
    未回答の追加質問を取得

    Args:
        user_id: ユーザーID
        conn: データベース接続

    Returns:
        未回答の質問リスト
    """

    result = conn.execute(
        sqlalchemy.text(
            """
            SELECT id, question_text, question_type, question_key, options, display_order
            FROM follow_up_questions
            WHERE user_id = :user_id AND is_answered = false
            ORDER BY display_order
            """
        ),
        {'user_id': user_id}
    )

    questions = []
    for row in result:
        questions.append({
            'id': str(row[0]),
            'question_text': row[1],
            'question_type': row[2],
            'question_key': row[3],
            'options': row[4],
            'display_order': row[5]
        })

    return questions


def save_answer(user_id: str, question_key: str, answer: str, conn):
    """
    追加質問の回答を保存

    Args:
        user_id: ユーザーID
        question_key: 質問キー
        answer: 回答
        conn: データベース接続
    """

    # follow_up_questionsテーブルを更新
    conn.execute(
        sqlalchemy.text(
            """
            UPDATE follow_up_questions
            SET answer = :answer, is_answered = true, answered_at = :answered_at
            WHERE user_id = :user_id AND question_key = :question_key
            """
        ),
        {
            'answer': answer,
            'answered_at': datetime.now(),
            'user_id': user_id,
            'question_key': question_key
        }
    )

    # user_profilesテーブルも更新（該当するカラムがある場合）
    profile_columns = [
        'has_pension', 'has_care_insurance', 'has_real_estate',
        'has_vehicle', 'has_life_insurance', 'is_self_employed',
        'is_dependent_family', 'has_children',
        'has_bank_account', 'has_credit_card', 'has_mobile_contract', 'has_subscription'
    ]
    if question_key in profile_columns:
        boolean_answer = answer.lower() in ['はい', 'yes', 'true', '1']
        conn.execute(
            sqlalchemy.text(f"""
                UPDATE user_profiles
                SET {question_key} = :answer
                WHERE user_id = :user_id
            """),
            {'answer': boolean_answer, 'user_id': user_id}
        )

        # はいの場合、連動質問（サービス詳細選択）を生成
        if boolean_answer and question_key in FOLLOW_UP_SERVICE_QUESTIONS:
            _create_service_selection_question(user_id, question_key, conn)

    conn.commit()


def check_all_questions_answered(user_id: str, conn) -> bool:
    """
    すべての追加質問に回答済みか確認

    Args:
        user_id: ユーザーID
        conn: データベース接続

    Returns:
        すべて回答済みの場合True
    """

    result = conn.execute(
        sqlalchemy.text(
            """
            SELECT COUNT(*) FROM follow_up_questions
            WHERE user_id = :user_id AND is_answered = false
            """
        ),
        {'user_id': user_id}
    ).fetchone()

    return result[0] == 0


def get_user_answers(user_id: str, conn) -> Dict[str, str]:
    """
    ユーザーの回答をすべて取得

    Args:
        user_id: ユーザーID
        conn: データベース接続

    Returns:
        {question_key: answer} の辞書
    """

    result = conn.execute(
        sqlalchemy.text(
            """
            SELECT question_key, answer
            FROM follow_up_questions
            WHERE user_id = :user_id AND is_answered = true
            """
        ),
        {'user_id': user_id}
    )

    answers = {}
    for row in result:
        answers[row[0]] = row[1]

    return answers


def format_question_for_line(question: Dict) -> str:
    """
    LINE用に質問をフォーマット

    Args:
        question: 質問情報

    Returns:
        フォーマットされた質問文
    """

    text = question['question_text']

    if question['question_type'] == 'yes_no':
        text += "\n\n「はい」または「いいえ」でお答えください。"
    elif question['question_type'] == 'multiple_choice' and question.get('options'):
        text += "\n\n以下から選択してください：\n"
        for i, option in enumerate(question['options'], 1):
            text += f"{i}. {option}\n"
    elif question['question_type'] == 'multiple_select':
        text += "\n\n複数選択可能です。選び終わったら「選択完了」を押してください。"

    return text


def _create_service_selection_question(user_id: str, parent_question_key: str, conn):
    """
    サービス詳細選択の連動質問を作成

    Args:
        user_id: ユーザーID
        parent_question_key: 親質問のキー（has_life_insurance等）
        conn: データベース接続
    """
    follow_up_config = FOLLOW_UP_SERVICE_QUESTIONS.get(parent_question_key)
    if not follow_up_config:
        return

    question_key = follow_up_config["question_key"]
    service_type = follow_up_config["service_type"]

    # 既に存在するか確認
    existing = conn.execute(
        sqlalchemy.text(
            """
            SELECT id FROM follow_up_questions
            WHERE user_id = :user_id AND question_key = :question_key
            """
        ),
        {'user_id': user_id, 'question_key': question_key}
    ).fetchone()

    if existing:
        return

    # 親質問のdisplay_orderを取得して、その直後に挿入
    parent_order = conn.execute(
        sqlalchemy.text(
            """
            SELECT display_order FROM follow_up_questions
            WHERE user_id = :user_id AND question_key = :parent_key
            """
        ),
        {'user_id': user_id, 'parent_key': parent_question_key}
    ).fetchone()

    new_order = (parent_order[0] if parent_order else 0) + 0.5

    # 選択肢を取得
    options = get_provider_names_for_quick_reply(service_type, max_items=12)

    conn.execute(
        sqlalchemy.text(
            """
            INSERT INTO follow_up_questions (
                user_id, question_text, question_type, question_key,
                options, display_order, parent_question_key, trigger_answer
            )
            VALUES (
                :user_id, :question_text, :question_type, :question_key,
                :options, :display_order, :parent_key, :trigger_answer
            )
            """
        ),
        {
            'user_id': user_id,
            'question_text': follow_up_config["question_text"],
            'question_type': 'multiple_select',
            'question_key': question_key,
            'options': json.dumps(options, ensure_ascii=False),
            'display_order': new_order,
            'parent_key': parent_question_key,
            'trigger_answer': 'はい'
        }
    )


def save_service_selection(user_id: str, question_key: str, service_name: str, conn):
    """
    ユーザーが選択したサービス（保険会社・銀行等）を保存

    Args:
        user_id: ユーザーID
        question_key: 質問キー（life_insurance_providers等）
        service_name: 選択されたサービス名
        conn: データベース接続
    """
    # question_keyからservice_typeを特定
    service_type_map = {
        'life_insurance_providers': 'life_insurance',
        'bank_providers': 'bank',
        'credit_card_providers': 'credit_card',
        'mobile_carrier_providers': 'mobile_carrier',
        'subscription_providers': 'subscription',
    }

    service_type = service_type_map.get(question_key)
    if not service_type:
        return

    # 「選択完了」「該当なし」は保存しない
    if service_name in ['選択完了', '該当なし']:
        return

    # 既に同じサービスが登録されているか確認
    existing = conn.execute(
        sqlalchemy.text(
            """
            SELECT id FROM user_services
            WHERE user_id = :user_id AND service_type = :service_type AND service_name = :service_name
            """
        ),
        {'user_id': user_id, 'service_type': service_type, 'service_name': service_name}
    ).fetchone()

    if existing:
        return

    # 「その他」の場合はcustom_nameフラグを設定
    is_custom = service_name == 'その他'

    conn.execute(
        sqlalchemy.text(
            """
            INSERT INTO user_services (user_id, service_type, service_name, custom_name)
            VALUES (:user_id, :service_type, :service_name, :custom_name)
            """
        ),
        {
            'user_id': user_id,
            'service_type': service_type,
            'service_name': service_name,
            'custom_name': None  # 後で「その他」の詳細入力時に更新
        }
    )
    conn.commit()


def complete_service_selection(user_id: str, question_key: str, conn):
    """
    サービス選択を完了としてマーク

    Args:
        user_id: ユーザーID
        question_key: 質問キー
        conn: データベース接続
    """
    # 選択されたサービスを取得してanswer欄に保存
    service_type_map = {
        'life_insurance_providers': 'life_insurance',
        'bank_providers': 'bank',
        'credit_card_providers': 'credit_card',
        'mobile_carrier_providers': 'mobile_carrier',
        'subscription_providers': 'subscription',
    }
    service_type = service_type_map.get(question_key)

    if service_type:
        services = conn.execute(
            sqlalchemy.text(
                """
                SELECT service_name FROM user_services
                WHERE user_id = :user_id AND service_type = :service_type
                """
            ),
            {'user_id': user_id, 'service_type': service_type}
        ).fetchall()

        answer = ', '.join([s[0] for s in services]) if services else '該当なし'
    else:
        answer = '選択完了'

    conn.execute(
        sqlalchemy.text(
            """
            UPDATE follow_up_questions
            SET answer = :answer, is_answered = true, answered_at = :answered_at
            WHERE user_id = :user_id AND question_key = :question_key
            """
        ),
        {
            'answer': answer,
            'answered_at': datetime.now(),
            'user_id': user_id,
            'question_key': question_key
        }
    )
    conn.commit()


def get_user_selected_services(user_id: str, conn) -> Dict[str, List[str]]:
    """
    ユーザーが選択したサービスを取得

    Args:
        user_id: ユーザーID
        conn: データベース接続

    Returns:
        {service_type: [service_name, ...]} の辞書
    """
    result = conn.execute(
        sqlalchemy.text(
            """
            SELECT service_type, service_name, custom_name
            FROM user_services
            WHERE user_id = :user_id
            ORDER BY service_type, created_at
            """
        ),
        {'user_id': user_id}
    )

    services = {}
    for row in result:
        service_type = row[0]
        service_name = row[2] if row[2] else row[1]  # custom_nameがあればそちらを使用
        if service_type not in services:
            services[service_type] = []
        services[service_type].append(service_name)

    return services


def is_service_selection_question(question_key: str) -> bool:
    """質問がサービス選択質問かどうかを判定"""
    return question_key.endswith('_providers')
