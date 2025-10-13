"""
追加質問生成モジュール

基本タスク生成後に、ユーザーの詳細な状況を把握するための
追加質問を動的に生成する
"""

from typing import List, Dict, Optional
import sqlalchemy
from datetime import datetime, timedelta


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
            question_text="故人は自営業でしたか？",
            question_key="is_self_employed",
            question_type="yes_no",
            display_order=6
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
                display_order=7
            )
        )
        questions.append(
            FollowUpQuestion(
                question_text="お子様はいらっしゃいますか？",
                question_key="has_children",
                question_type="yes_no",
                display_order=8
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
                    'options': sqlalchemy.text('NULL') if not question.options else str(question.options),
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
    if question_key in [
        'has_pension', 'has_care_insurance', 'has_real_estate',
        'has_vehicle', 'has_life_insurance', 'is_self_employed',
        'is_dependent_family', 'has_children'
    ]:
        boolean_answer = answer.lower() in ['はい', 'yes', 'true', '1']
        conn.execute(
            sqlalchemy.text(f"""
                UPDATE user_profiles
                SET {question_key} = :answer
                WHERE user_id = :user_id
            """),
            {'answer': boolean_answer, 'user_id': user_id}
        )

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

    return text
