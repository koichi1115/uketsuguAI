"""
プライバシー保護ユーティリティモジュール

外部APIに送信する前に個人情報を匿名化・一般化
"""

from typing import Dict, Any, Optional
from datetime import datetime, date
import hashlib


def anonymize_profile_for_ai(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    AIサービスに送信するプロファイルデータを匿名化

    個人を特定できる情報を削除・一般化し、AIタスク生成に
    必要な情報のみを残す

    Args:
        profile: 元のプロファイルデータ
            - relationship: 故人との関係
            - prefecture: 都道府県
            - municipality: 市区町村
            - death_date: 死亡日

    Returns:
        匿名化されたプロファイルデータ
    """
    anonymized = {}

    # 関係性は一般化（例：「母」→「親」）
    if 'relationship' in profile:
        anonymized['relationship'] = generalize_relationship(profile['relationship'])

    # 都道府県は地域レベルに一般化
    if 'prefecture' in profile:
        anonymized['region'] = generalize_prefecture_to_region(profile['prefecture'])

    # 市区町村は含めない（特定リスクが高いため）
    # municipality は送信しない

    # 死亡日は経過期間に変換（日付そのものは送信しない）
    if 'death_date' in profile and profile['death_date']:
        anonymized['time_since_death'] = calculate_time_since_death(profile['death_date'])

    return anonymized


def generalize_relationship(relationship: str) -> str:
    """
    関係性を一般化

    Args:
        relationship: 具体的な関係性（例：母、父、祖母）

    Returns:
        一般化された関係性（例：親、祖父母）
    """
    # 親世代
    if relationship in ['父', '母', '義父', '義母', 'お父さん', 'お母さん', '親']:
        return '親'

    # 祖父母世代
    if relationship in ['祖父', '祖母', '義祖父', '義祖母', 'おじいちゃん', 'おばあちゃん', '祖父母']:
        return '祖父母'

    # 配偶者
    if relationship in ['夫', '妻', '配偶者', 'パートナー']:
        return '配偶者'

    # 子供
    if relationship in ['息子', '娘', '子', '子供']:
        return '子'

    # 兄弟姉妹
    if relationship in ['兄', '弟', '姉', '妹', '兄弟', '姉妹', '兄弟姉妹']:
        return '兄弟姉妹'

    # その他の親族
    return '親族'


def generalize_prefecture_to_region(prefecture: str) -> str:
    """
    都道府県を地域ブロックに一般化

    Args:
        prefecture: 都道府県名

    Returns:
        地域ブロック名
    """
    regions = {
        '北海道': ['北海道'],
        '東北': ['青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県'],
        '関東': ['茨城県', '栃木県', '群馬県', '埼玉県', '千葉県', '東京都', '神奈川県'],
        '中部': ['新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県', '岐阜県', '静岡県', '愛知県'],
        '近畿': ['三重県', '滋賀県', '京都府', '大阪府', '兵庫県', '奈良県', '和歌山県'],
        '中国': ['鳥取県', '島根県', '岡山県', '広島県', '山口県'],
        '四国': ['徳島県', '香川県', '愛媛県', '高知県'],
        '九州・沖縄': ['福岡県', '佐賀県', '長崎県', '熊本県', '大分県', '宮崎県', '鹿児島県', '沖縄県']
    }

    for region, prefs in regions.items():
        if prefecture in prefs:
            return region

    return '日本'


def calculate_time_since_death(death_date) -> str:
    """
    死亡日からの経過期間を計算

    Args:
        death_date: 死亡日（datetime.date または datetime.datetime）

    Returns:
        経過期間の説明（例：「1ヶ月未満」「3-6ヶ月」）
    """
    if isinstance(death_date, str):
        death_date = datetime.fromisoformat(death_date).date()
    elif isinstance(death_date, datetime):
        death_date = death_date.date()

    today = date.today()
    delta = today - death_date
    days = delta.days

    if days < 7:
        return '1週間未満'
    elif days < 30:
        return '1ヶ月未満'
    elif days < 90:
        return '1-3ヶ月'
    elif days < 180:
        return '3-6ヶ月'
    elif days < 365:
        return '6ヶ月-1年'
    elif days < 730:
        return '1-2年'
    else:
        years = days // 365
        return f'{years}年以上'


def create_privacy_notice() -> str:
    """
    プライバシー保護に関する通知メッセージを生成

    Returns:
        通知メッセージ
    """
    return """
【プライバシー保護について】
AIタスク生成では、あなたの個人情報を保護するため、以下の対策を実施しています：
- 住所は地域レベルに一般化
- 日付は経過期間に変換
- 個人を特定できる情報は送信されません
"""


def hash_user_id(user_id: str) -> str:
    """
    ユーザーIDをハッシュ化（ログ記録用）

    Args:
        user_id: 元のユーザーID

    Returns:
        ハッシュ化されたID（最初の8文字）
    """
    hash_object = hashlib.sha256(user_id.encode())
    return hash_object.hexdigest()[:8]
