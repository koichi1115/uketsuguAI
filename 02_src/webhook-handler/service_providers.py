"""
サービス提供者マスターデータ

保険会社、銀行、携帯キャリア等の主要なサービス提供者リストを定義
LLMによる個別タスク生成時に使用
"""

from typing import Dict, List, TypedDict


class ServiceProvider(TypedDict):
    """サービス提供者の定義"""
    name: str           # 表示名
    code: str           # 内部コード
    search_keyword: str # LLM検索用キーワード


class ServiceCategory(TypedDict):
    """サービスカテゴリの定義"""
    label: str                      # 質問表示用ラベル
    question_text: str              # 質問文
    task_template: str              # タスク名テンプレート
    providers: List[ServiceProvider]


# =============================================================================
# 生命保険会社
# =============================================================================
LIFE_INSURANCE_PROVIDERS: List[ServiceProvider] = [
    {"name": "日本生命", "code": "nissay", "search_keyword": "日本生命 死亡保険金 請求 手続き"},
    {"name": "第一生命", "code": "dai-ichi", "search_keyword": "第一生命 死亡保険金 請求 手続き"},
    {"name": "住友生命", "code": "sumitomo", "search_keyword": "住友生命 死亡保険金 請求 手続き"},
    {"name": "明治安田生命", "code": "meijiyasuda", "search_keyword": "明治安田生命 死亡保険金 請求 手続き"},
    {"name": "アフラック", "code": "aflac", "search_keyword": "アフラック 死亡保険金 請求 手続き"},
    {"name": "メットライフ生命", "code": "metlife", "search_keyword": "メットライフ生命 死亡保険金 請求 手続き"},
    {"name": "ソニー生命", "code": "sony", "search_keyword": "ソニー生命 死亡保険金 請求 手続き"},
    {"name": "オリックス生命", "code": "orix", "search_keyword": "オリックス生命 死亡保険金 請求 手続き"},
    {"name": "かんぽ生命", "code": "kampo", "search_keyword": "かんぽ生命 死亡保険金 請求 手続き"},
    {"name": "朝日生命", "code": "asahi", "search_keyword": "朝日生命 死亡保険金 請求 手続き"},
    {"name": "太陽生命", "code": "taiyo", "search_keyword": "太陽生命 死亡保険金 請求 手続き"},
    {"name": "富国生命", "code": "fukoku", "search_keyword": "富国生命 死亡保険金 請求 手続き"},
    {"name": "大同生命", "code": "daido", "search_keyword": "大同生命 死亡保険金 請求 手続き"},
    {"name": "プルデンシャル生命", "code": "prudential", "search_keyword": "プルデンシャル生命 死亡保険金 請求 手続き"},
    {"name": "ジブラルタ生命", "code": "gibraltar", "search_keyword": "ジブラルタ生命 死亡保険金 請求 手続き"},
    {"name": "SBI生命", "code": "sbi-life", "search_keyword": "SBI生命 死亡保険金 請求 手続き"},
    {"name": "楽天生命", "code": "rakuten-life", "search_keyword": "楽天生命 死亡保険金 請求 手続き"},
    {"name": "ライフネット生命", "code": "lifenet", "search_keyword": "ライフネット生命 死亡保険金 請求 手続き"},
]

# =============================================================================
# 銀行
# =============================================================================
BANK_PROVIDERS: List[ServiceProvider] = [
    {"name": "三菱UFJ銀行", "code": "mufg", "search_keyword": "三菱UFJ銀行 相続 手続き 必要書類"},
    {"name": "三井住友銀行", "code": "smbc", "search_keyword": "三井住友銀行 相続 手続き 必要書類"},
    {"name": "みずほ銀行", "code": "mizuho", "search_keyword": "みずほ銀行 相続 手続き 必要書類"},
    {"name": "りそな銀行", "code": "resona", "search_keyword": "りそな銀行 相続 手続き 必要書類"},
    {"name": "ゆうちょ銀行", "code": "yucho", "search_keyword": "ゆうちょ銀行 相続 手続き 必要書類"},
    {"name": "横浜銀行", "code": "yokohama", "search_keyword": "横浜銀行 相続 手続き 必要書類"},
    {"name": "千葉銀行", "code": "chiba", "search_keyword": "千葉銀行 相続 手続き 必要書類"},
    {"name": "静岡銀行", "code": "shizuoka", "search_keyword": "静岡銀行 相続 手続き 必要書類"},
    {"name": "福岡銀行", "code": "fukuoka", "search_keyword": "福岡銀行 相続 手続き 必要書類"},
    {"name": "北海道銀行", "code": "hokkaido", "search_keyword": "北海道銀行 相続 手続き 必要書類"},
    {"name": "京都銀行", "code": "kyoto", "search_keyword": "京都銀行 相続 手続き 必要書類"},
    {"name": "広島銀行", "code": "hiroshima", "search_keyword": "広島銀行 相続 手続き 必要書類"},
    {"name": "楽天銀行", "code": "rakuten-bank", "search_keyword": "楽天銀行 相続 手続き 必要書類"},
    {"name": "住信SBIネット銀行", "code": "sbi-net", "search_keyword": "住信SBIネット銀行 相続 手続き 必要書類"},
    {"name": "PayPay銀行", "code": "paypay", "search_keyword": "PayPay銀行 相続 手続き 必要書類"},
    {"name": "イオン銀行", "code": "aeon", "search_keyword": "イオン銀行 相続 手続き 必要書類"},
    {"name": "auじぶん銀行", "code": "aujibun", "search_keyword": "auじぶん銀行 相続 手続き 必要書類"},
    {"name": "セブン銀行", "code": "seven", "search_keyword": "セブン銀行 相続 手続き 必要書類"},
]

# =============================================================================
# クレジットカード会社
# =============================================================================
CREDIT_CARD_PROVIDERS: List[ServiceProvider] = [
    {"name": "JCB", "code": "jcb", "search_keyword": "JCBカード 死亡 解約 手続き"},
    {"name": "三井住友カード", "code": "smcc", "search_keyword": "三井住友カード 死亡 解約 手続き"},
    {"name": "三菱UFJニコス", "code": "mufg-nicos", "search_keyword": "三菱UFJニコス 死亡 解約 手続き"},
    {"name": "楽天カード", "code": "rakuten-card", "search_keyword": "楽天カード 死亡 解約 手続き"},
    {"name": "イオンカード", "code": "aeon-card", "search_keyword": "イオンカード 死亡 解約 手続き"},
    {"name": "エポスカード", "code": "epos", "search_keyword": "エポスカード 死亡 解約 手続き"},
    {"name": "オリコカード", "code": "orico", "search_keyword": "オリコカード 死亡 解約 手続き"},
    {"name": "セゾンカード", "code": "saison", "search_keyword": "セゾンカード 死亡 解約 手続き"},
    {"name": "dカード", "code": "dcard", "search_keyword": "dカード 死亡 解約 手続き"},
    {"name": "PayPayカード", "code": "paypay-card", "search_keyword": "PayPayカード 死亡 解約 手続き"},
    {"name": "au PAYカード", "code": "aupay", "search_keyword": "au PAYカード 死亡 解約 手続き"},
    {"name": "アメリカン・エキスプレス", "code": "amex", "search_keyword": "アメックス 死亡 解約 手続き"},
    {"name": "ダイナースクラブ", "code": "diners", "search_keyword": "ダイナースクラブ 死亡 解約 手続き"},
]

# =============================================================================
# 携帯電話キャリア
# =============================================================================
MOBILE_CARRIER_PROVIDERS: List[ServiceProvider] = [
    {"name": "ドコモ", "code": "docomo", "search_keyword": "ドコモ 死亡 解約 名義変更 手続き"},
    {"name": "au", "code": "au", "search_keyword": "au 死亡 解約 名義変更 手続き"},
    {"name": "ソフトバンク", "code": "softbank", "search_keyword": "ソフトバンク 死亡 解約 名義変更 手続き"},
    {"name": "楽天モバイル", "code": "rakuten-mobile", "search_keyword": "楽天モバイル 死亡 解約 手続き"},
    {"name": "UQモバイル", "code": "uq", "search_keyword": "UQモバイル 死亡 解約 手続き"},
    {"name": "ワイモバイル", "code": "ymobile", "search_keyword": "ワイモバイル 死亡 解約 手続き"},
    {"name": "ahamo", "code": "ahamo", "search_keyword": "ahamo 死亡 解約 手続き"},
    {"name": "povo", "code": "povo", "search_keyword": "povo 死亡 解約 手続き"},
    {"name": "LINEMO", "code": "linemo", "search_keyword": "LINEMO 死亡 解約 手続き"},
    {"name": "IIJmio", "code": "iijmio", "search_keyword": "IIJmio 死亡 解約 手続き"},
    {"name": "mineo", "code": "mineo", "search_keyword": "mineo 死亡 解約 手続き"},
]

# =============================================================================
# サブスクリプションサービス
# =============================================================================
SUBSCRIPTION_PROVIDERS: List[ServiceProvider] = [
    {"name": "Netflix", "code": "netflix", "search_keyword": "Netflix 死亡 解約 手続き"},
    {"name": "Amazon Prime", "code": "amazon-prime", "search_keyword": "Amazon Prime 死亡 解約 手続き"},
    {"name": "Disney+", "code": "disney-plus", "search_keyword": "Disney+ 死亡 解約 手続き"},
    {"name": "YouTube Premium", "code": "youtube-premium", "search_keyword": "YouTube Premium 解約 手続き"},
    {"name": "Spotify", "code": "spotify", "search_keyword": "Spotify 死亡 解約 手続き"},
    {"name": "Apple Music", "code": "apple-music", "search_keyword": "Apple Music 解約 手続き"},
    {"name": "NHKオンデマンド", "code": "nhk-ondemand", "search_keyword": "NHKオンデマンド 解約 手続き"},
    {"name": "DAZN", "code": "dazn", "search_keyword": "DAZN 死亡 解約 手続き"},
    {"name": "U-NEXT", "code": "unext", "search_keyword": "U-NEXT 死亡 解約 手続き"},
    {"name": "Hulu", "code": "hulu", "search_keyword": "Hulu 死亡 解約 手続き"},
    {"name": "スカパー!", "code": "skyperfect", "search_keyword": "スカパー 死亡 解約 手続き"},
    {"name": "WOWOW", "code": "wowow", "search_keyword": "WOWOW 死亡 解約 手続き"},
    {"name": "新聞（紙面）", "code": "newspaper", "search_keyword": "新聞 死亡 解約 手続き"},
]

# =============================================================================
# 公共料金
# =============================================================================
UTILITY_PROVIDERS: List[ServiceProvider] = [
    {"name": "電気（東京電力）", "code": "tepco", "search_keyword": "東京電力 死亡 名義変更 手続き"},
    {"name": "電気（関西電力）", "code": "kepco", "search_keyword": "関西電力 死亡 名義変更 手続き"},
    {"name": "電気（中部電力）", "code": "chuden", "search_keyword": "中部電力 死亡 名義変更 手続き"},
    {"name": "電気（その他）", "code": "other-electric", "search_keyword": "電力会社 死亡 名義変更 手続き"},
    {"name": "ガス（東京ガス）", "code": "tokyo-gas", "search_keyword": "東京ガス 死亡 名義変更 手続き"},
    {"name": "ガス（大阪ガス）", "code": "osaka-gas", "search_keyword": "大阪ガス 死亡 名義変更 手続き"},
    {"name": "ガス（その他）", "code": "other-gas", "search_keyword": "ガス会社 死亡 名義変更 手続き"},
    {"name": "水道", "code": "water", "search_keyword": "水道 死亡 名義変更 手続き"},
    {"name": "NHK", "code": "nhk", "search_keyword": "NHK 死亡 解約 名義変更 手続き"},
    {"name": "固定電話", "code": "landline", "search_keyword": "固定電話 NTT 死亡 解約 手続き"},
    {"name": "インターネット回線", "code": "internet", "search_keyword": "インターネット回線 死亡 解約 手続き"},
]


# =============================================================================
# サービスカテゴリ定義（質問生成用）
# =============================================================================
SERVICE_CATEGORIES: Dict[str, ServiceCategory] = {
    "life_insurance": {
        "label": "生命保険",
        "question_text": "加入している保険会社を選んでください（複数選択可）",
        "task_template": "{provider}の死亡保険金請求",
        "providers": LIFE_INSURANCE_PROVIDERS,
    },
    "bank": {
        "label": "銀行",
        "question_text": "口座をお持ちの銀行を選んでください（複数選択可）",
        "task_template": "{provider}の相続手続き",
        "providers": BANK_PROVIDERS,
    },
    "credit_card": {
        "label": "クレジットカード",
        "question_text": "お持ちのクレジットカードを選んでください（複数選択可）",
        "task_template": "{provider}の解約手続き",
        "providers": CREDIT_CARD_PROVIDERS,
    },
    "mobile_carrier": {
        "label": "携帯電話",
        "question_text": "契約している携帯会社を選んでください（複数選択可）",
        "task_template": "{provider}の解約/名義変更",
        "providers": MOBILE_CARRIER_PROVIDERS,
    },
    "subscription": {
        "label": "サブスクリプション",
        "question_text": "契約しているサービスを選んでください（複数選択可）",
        "task_template": "{provider}の解約",
        "providers": SUBSCRIPTION_PROVIDERS,
    },
    "utility": {
        "label": "公共料金",
        "question_text": "契約しているサービスを選んでください（複数選択可）",
        "task_template": "{provider}の名義変更/解約",
        "providers": UTILITY_PROVIDERS,
    },
}


def get_providers_for_type(service_type: str) -> List[ServiceProvider]:
    """指定されたサービスタイプの提供者リストを取得"""
    category = SERVICE_CATEGORIES.get(service_type)
    if category:
        return category["providers"]
    return []


def get_provider_names_for_quick_reply(service_type: str, max_items: int = 10) -> List[str]:
    """
    LINE Quick Reply用の選択肢を取得（最大数制限あり）

    Args:
        service_type: サービスタイプ
        max_items: 最大表示数（LINE Quick Replyは13個まで）

    Returns:
        表示用の選択肢リスト（最後に「その他」「該当なし」を追加）
    """
    providers = get_providers_for_type(service_type)
    names = [p["name"] for p in providers[:max_items - 2]]  # 「その他」「該当なし」分を確保
    names.append("その他")
    names.append("選択完了")
    return names


def get_search_keyword(service_type: str, provider_name: str) -> str:
    """指定されたサービス・提供者の検索キーワードを取得"""
    providers = get_providers_for_type(service_type)
    for provider in providers:
        if provider["name"] == provider_name:
            return provider["search_keyword"]
    # その他の場合は汎用キーワード
    category = SERVICE_CATEGORIES.get(service_type, {})
    return f"{provider_name} 死亡 手続き"


def get_task_title(service_type: str, provider_name: str) -> str:
    """タスクタイトルを生成"""
    category = SERVICE_CATEGORIES.get(service_type, {})
    template = category.get("task_template", "{provider}の手続き")
    return template.format(provider=provider_name)


# 質問キーとサービスタイプのマッピング
QUESTION_KEY_TO_SERVICE_TYPE = {
    "has_life_insurance": "life_insurance",
    "has_bank_account": "bank",
    "has_credit_card": "credit_card",
    "has_mobile_contract": "mobile_carrier",
    "has_subscription": "subscription",
}

# 連動質問の定義（親質問がYesの場合に表示する詳細質問）
FOLLOW_UP_SERVICE_QUESTIONS = {
    "has_life_insurance": {
        "question_key": "life_insurance_providers",
        "question_text": "加入している保険会社を選んでください（複数選択可、選び終わったら「選択完了」を押してください）",
        "service_type": "life_insurance",
    },
    "has_bank_account": {
        "question_key": "bank_providers",
        "question_text": "口座をお持ちの銀行を選んでください（複数選択可、選び終わったら「選択完了」を押してください）",
        "service_type": "bank",
    },
    "has_credit_card": {
        "question_key": "credit_card_providers",
        "question_text": "お持ちのクレジットカードを選んでください（複数選択可、選び終わったら「選択完了」を押してください）",
        "service_type": "credit_card",
    },
    "has_mobile_contract": {
        "question_key": "mobile_carrier_providers",
        "question_text": "契約している携帯会社を選んでください（複数選択可、選び終わったら「選択完了」を押してください）",
        "service_type": "mobile_carrier",
    },
    "has_subscription": {
        "question_key": "subscription_providers",
        "question_text": "契約しているサービスを選んでください（複数選択可、選び終わったら「選択完了」を押してください）",
        "service_type": "subscription",
    },
}
