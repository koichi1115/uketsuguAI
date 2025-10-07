"""
Flex Message テンプレート
"""
import re


def parse_text_with_links(text):
    """
    テキストから電話番号とURLを検出してFlexコンポーネントのリストに変換

    Args:
        text: パースするテキスト

    Returns:
        Flexコンポーネントのリスト
    """
    if not text:
        return []

    # URLと電話番号のパターン
    url_pattern = r'https?://[^\s]+'
    phone_pattern = r'(\d{2,5}-\d{1,4}-\d{4}|\d{10,11}(?!\d))'

    # 両方のパターンを結合
    combined_pattern = f'({url_pattern}|{phone_pattern})'

    parts = []
    last_end = 0

    for match in re.finditer(combined_pattern, text):
        # マッチ前のテキスト
        if match.start() > last_end:
            before_text = text[last_end:match.start()]
            if before_text.strip():
                parts.append({
                    "type": "text",
                    "text": before_text,
                    "size": "sm",
                    "wrap": True,
                    "color": "#666666"
                })

        matched_text = match.group(0)

        # URLか電話番号かを判定
        if matched_text.startswith('http'):
            # URL
            parts.append({
                "type": "text",
                "text": matched_text,
                "size": "sm",
                "wrap": True,
                "color": "#0066CC",
                "decoration": "underline",
                "action": {
                    "type": "uri",
                    "uri": matched_text
                }
            })
        else:
            # 電話番号
            clean_phone = matched_text.replace('-', '')
            if clean_phone.startswith('0') and len(clean_phone) in [10, 11]:
                parts.append({
                    "type": "text",
                    "text": matched_text,
                    "size": "sm",
                    "wrap": True,
                    "color": "#0066CC",
                    "decoration": "underline",
                    "action": {
                        "type": "uri",
                        "uri": f"tel:{clean_phone}"
                    }
                })
            else:
                # 電話番号でない数字列
                parts.append({
                    "type": "text",
                    "text": matched_text,
                    "size": "sm",
                    "wrap": True,
                    "color": "#666666"
                })

        last_end = match.end()

    # 残りのテキスト
    if last_end < len(text):
        remaining_text = text[last_end:]
        if remaining_text.strip():
            parts.append({
                "type": "text",
                "text": remaining_text,
                "size": "sm",
                "wrap": True,
                "color": "#666666"
            })

    # パーツがない場合は元のテキストを返す
    if not parts:
        parts.append({
            "type": "text",
            "text": text,
            "size": "sm",
            "wrap": True,
            "color": "#666666"
        })

    return parts


def create_task_list_flex(tasks, user_name="", show_all=False):
    """
    タスク一覧のFlex Messageを生成（縦スクロール形式）

    Args:
        tasks: タスクのリスト [(id, title, due_date, status, priority, category), ...]
        user_name: ユーザー名（オプション）
        show_all: 全件表示するかどうか（デフォルトは先頭5件のみ）

    Returns:
        Flex Message JSON
    """

    # 未完了タスクと完了済みタスクを分離
    pending_tasks = [t for t in tasks if t[3] == 'pending']
    completed_tasks = [t for t in tasks if t[3] == 'completed']

    # タスクがない場合
    if not tasks:
        return {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "登録されているタスクはありません",
                        "wrap": True,
                        "color": "#999999",
                        "align": "center"
                    }
                ]
            }
        }

    # Bodyコンテンツを作成
    body_contents = []

    # 未完了タスク（show_all=Trueなら全件、Falseなら最大5件）
    display_count = len(pending_tasks) if show_all else min(5, len(pending_tasks))
    for i, task in enumerate(pending_tasks[:display_count]):
        task_id, title, due_date, status, priority, category = task

        # 優先度による絵文字設定
        priority_emoji = "🔴" if priority == "high" else "🟡" if priority == "medium" else "⚪"

        # 期限表示
        due_str = due_date.strftime("%m/%d") if due_date else "期限なし"

        # タスクボックス
        task_box = {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": priority_emoji,
                            "size": "sm",
                            "flex": 0
                        },
                        {
                            "type": "text",
                            "text": title,
                            "weight": "bold",
                            "size": "md",
                            "flex": 5,
                            "margin": "sm",
                            "wrap": True,
                            "color": "#333333"
                        }
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"期限: {due_str}",
                            "size": "xs",
                            "color": "#999999",
                            "flex": 1
                        },
                        {
                            "type": "text",
                            "text": category,
                            "size": "xs",
                            "color": "#999999",
                            "align": "end",
                            "flex": 1
                        }
                    ],
                    "margin": "sm"
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "📋 詳細",
                                "data": f"action=view_task_detail&task_id={task_id}",
                                "displayText": f"「{title}」の詳細"
                            },
                            "style": "link",
                            "height": "sm",
                            "flex": 1
                        },
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "✅ 完了",
                                "data": f"action=complete_task&task_id={task_id}",
                                "displayText": f"「{title}」を完了しました"
                            },
                            "style": "primary",
                            "color": "#17C964",
                            "height": "sm",
                            "flex": 1
                        }
                    ],
                    "spacing": "sm",
                    "margin": "md"
                }
            ],
            "paddingAll": "12px",
            "backgroundColor": "#FFFFFF",
            "cornerRadius": "8px",
            "margin": "md" if i > 0 else "none"
        }

        body_contents.append(task_box)

        # セパレーター（最後以外）
        if i < display_count - 1 or (not show_all and len(pending_tasks) > 5) or completed_tasks:
            body_contents.append({
                "type": "separator",
                "margin": "md"
            })

    # 「もっと見る」ボタン（6件以上ある場合で、show_all=Falseの時のみ）
    if not show_all and len(pending_tasks) > 5:
        body_contents.append({
            "type": "button",
            "action": {
                "type": "message",
                "label": f"もっと見る ({len(pending_tasks) - 5}件)",
                "text": "全タスク"
            },
            "style": "link",
            "height": "sm",
            "margin": "md"
        })

        if completed_tasks:
            body_contents.append({
                "type": "separator",
                "margin": "md"
            })

    # 完了済みタスクサマリー
    if completed_tasks:
        # ヘッダー
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"✅ 完了済み ({len(completed_tasks)}件)",
                    "weight": "bold",
                    "size": "sm",
                    "color": "#17C964"
                }
            ],
            "paddingAll": "12px",
            "backgroundColor": "#F0F0F0",
            "cornerRadius": "8px",
            "margin": "md"
        })

        # 完了済みタスク（show_all=Trueなら全件、Falseなら最新3件）
        completed_display_count = len(completed_tasks) if show_all else min(3, len(completed_tasks))
        for i, task in enumerate(completed_tasks[:completed_display_count]):
            task_id, title, due_date, status, priority, category = task

            # 完了済みタスクボックス（横並び）
            completed_task_box = {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "text",
                        "text": f"✅ {title}",
                        "size": "sm",
                        "color": "#666666",
                        "wrap": True,
                        "flex": 5
                    },
                    {
                        "type": "text",
                        "text": "↩️",
                        "size": "md",
                        "color": "#999999",
                        "flex": 0,
                        "align": "end",
                        "action": {
                            "type": "postback",
                            "data": f"action=uncomplete_task&task_id={task_id}",
                            "displayText": f"「{title}」を未完了に戻しました"
                        }
                    }
                ],
                "paddingAll": "8px",
                "backgroundColor": "#FAFAFA",
                "cornerRadius": "6px",
                "margin": "sm"
            }

            body_contents.append(completed_task_box)

    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "📋 タスク一覧",
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
            "contents": body_contents,
            "paddingAll": "15px"
        }
    }


def create_task_completed_flex(task_title):
    """タスク完了メッセージのFlex Message"""
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "✅ タスク完了",
                    "weight": "bold",
                    "color": "#17C964",
                    "size": "lg"
                },
                {
                    "type": "text",
                    "text": task_title,
                    "wrap": True,
                    "color": "#333333",
                    "margin": "md"
                },
                {
                    "type": "separator",
                    "margin": "lg"
                },
                {
                    "type": "text",
                    "text": "お疲れ様でした！",
                    "size": "sm",
                    "color": "#999999",
                    "margin": "lg",
                    "align": "center"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "タスク一覧を見る",
                        "text": "タスク"
                    },
                    "style": "link",
                    "height": "sm"
                }
            ]
        }
    }


def create_task_detail_flex(task_info):
    """
    タスク詳細のFlex Messageを生成

    Args:
        task_info: タスク情報 (id, title, description, due_date, priority, category)

    Returns:
        Flex Message JSON
    """
    task_id, title, description, due_date, priority, category = task_info

    # 優先度による絵文字設定
    priority_emoji = "🔴" if priority == "high" else "🟡" if priority == "medium" else "⚪"
    priority_text = "高" if priority == "high" else "中" if priority == "medium" else "低"

    # 期限表示
    due_str = due_date.strftime("%Y年%m月%d日") if due_date else "期限なし"

    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "📋 タスク詳細",
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
                {
                    "type": "text",
                    "text": title,
                    "weight": "bold",
                    "size": "xl",
                    "wrap": True,
                    "color": "#333333"
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "baseline",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": priority_emoji,
                                    "size": "sm",
                                    "flex": 0
                                },
                                {
                                    "type": "text",
                                    "text": f"優先度: {priority_text}",
                                    "size": "sm",
                                    "color": "#999999",
                                    "margin": "sm",
                                    "flex": 0
                                }
                            ],
                            "flex": 1
                        },
                        {
                            "type": "text",
                            "text": category,
                            "size": "xs",
                            "color": "#999999",
                            "align": "end",
                            "flex": 1
                        }
                    ],
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "baseline",
                    "contents": [
                        {
                            "type": "text",
                            "text": "📅",
                            "size": "sm",
                            "flex": 0
                        },
                        {
                            "type": "text",
                            "text": f"期限: {due_str}",
                            "size": "sm",
                            "color": "#999999",
                            "margin": "sm",
                            "flex": 1
                        }
                    ],
                    "margin": "sm"
                },
                {
                    "type": "separator",
                    "margin": "lg"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": parse_text_with_links(description),
                    "margin": "lg",
                    "spacing": "xs"
                }
            ],
            "paddingAll": "20px"
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "タスク一覧に戻る",
                        "text": "タスク"
                    },
                    "style": "link",
                    "height": "sm"
                }
            ],
            "paddingAll": "15px"
        }
    }
