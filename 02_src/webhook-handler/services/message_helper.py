"""
メッセージヘルパーモジュール
ヘルプメッセージと設定メッセージの生成
"""


def get_help_message() -> str:
    """ヘルプメッセージを生成"""
    return """【受け継ぐAI 使い方ガイド】

🤖 **受け継ぐAIとは**
大切な方が亡くなられた後の行政手続きをサポートするLINE Botです。

📋 **主な機能**
1. タスク管理
   - 必要な手続きを自動でリストアップ
   - 期限・優先度を表示
   - 完了したタスクにチェック

2. AI相談
   - 手続きに関する質問に回答
   - 行政ナレッジベースを活用

3. リッチメニュー
   - タスク一覧：やるべきことを確認
   - AI相談：質問や相談
   - 設定：プロフィール確認
   - ヘルプ：このメッセージ

📞 **お問い合わせ**
ko_15_ko_15-m1@yahoo.co.jp

💡 **ヒント**
- 「タスク」でタスク一覧を表示
- 「全タスク」で完了済み含む全て表示
- 質問は自由に入力してください"""


def get_settings_message(user_id: str, relationship: str, prefecture: str, municipality: str, death_date):
    """設定メッセージを生成（FlexMessage形式）"""
    # 死亡日をフォーマット
    death_date_str = death_date.strftime("%Y年%m月%d日") if death_date else "未設定"

    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "⚙️ 設定",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#333333"
                }
            ],
            "paddingAll": "15px",
            "backgroundColor": "#F7F7F7"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                # 故人との関係
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "👤 故人との関係",
                            "size": "sm",
                            "color": "#999999",
                            "weight": "bold"
                        },
                        {
                            "type": "text",
                            "text": relationship or "未設定",
                            "size": "md",
                            "color": "#333333",
                            "wrap": True,
                            "margin": "sm"
                        },
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "変更",
                                "data": "action=edit_relationship",
                                "displayText": "故人との関係を変更"
                            },
                            "style": "link",
                            "height": "sm",
                            "margin": "sm"
                        }
                    ],
                    "paddingAll": "12px",
                    "backgroundColor": "#FAFAFA",
                    "cornerRadius": "8px"
                },
                # お住まい
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "📍 お住まい",
                            "size": "sm",
                            "color": "#999999",
                            "weight": "bold"
                        },
                        {
                            "type": "text",
                            "text": f"{prefecture or '未設定'} {municipality or ''}",
                            "size": "md",
                            "color": "#333333",
                            "wrap": True,
                            "margin": "sm"
                        },
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "変更",
                                "data": "action=edit_address",
                                "displayText": "お住まいを変更"
                            },
                            "style": "link",
                            "height": "sm",
                            "margin": "sm"
                        }
                    ],
                    "paddingAll": "12px",
                    "backgroundColor": "#FAFAFA",
                    "cornerRadius": "8px",
                    "margin": "md"
                },
                # 死亡日
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "📅 死亡日",
                            "size": "sm",
                            "color": "#999999",
                            "weight": "bold"
                        },
                        {
                            "type": "text",
                            "text": death_date_str,
                            "size": "md",
                            "color": "#333333",
                            "wrap": True,
                            "margin": "sm"
                        },
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "変更",
                                "data": "action=edit_death_date",
                                "displayText": "死亡日を変更"
                            },
                            "style": "link",
                            "height": "sm",
                            "margin": "sm"
                        }
                    ],
                    "paddingAll": "12px",
                    "backgroundColor": "#FAFAFA",
                    "cornerRadius": "8px",
                    "margin": "md"
                },
                # 注意書き
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "💡 死亡日を変更すると、タスクの期限も再計算されます。",
                            "size": "xs",
                            "color": "#999999",
                            "wrap": True
                        }
                    ],
                    "margin": "lg"
                }
            ],
            "paddingAll": "20px"
        }
    }
