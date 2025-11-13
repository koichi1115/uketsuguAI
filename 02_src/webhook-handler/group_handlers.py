"""
グループイベントハンドラー関数
main.pyに統合するための一時ファイル
"""

# このファイルの内容をmain.pyの末尾に追加してください

GROUP_HANDLERS_CODE = '''

# ============================================
# グループイベントハンドラー
# ============================================

def handle_group_join(event):
    """ボットがグループに追加されたときの処理"""
    line_group_id = event.source.group_id
    configuration = get_configuration()
    engine = get_db_engine()
    group_manager = GroupManager(engine)

    print(f"🎉 グループ参加イベント: line_group_id={line_group_id}")

    existing_group = group_manager.get_group_by_line_id(line_group_id)

    if existing_group:
        message = "✅ グループに再追加されました！\\n\\n「タスク」と送信してタスクリストを確認してください。"
    else:
        message = """👋 こんにちは！受け継ぐAIです。

グループでのご利用には、以下の手順が必要です：

1️⃣ まず、個人チャットで以下を完了してください：
   • プロフィール登録
   • 有料プランへのアップグレード

2️⃣ 完了後、改めてこのグループに追加してください

3️⃣ グループ追加完了後、以下が利用可能になります：
   • タスク一覧の閲覧
   • タスクの担当者割り当て
   • タスクの完了報告

※ 有料プランで1グループまで追加可能です

まずは個人チャットで「受け継ぐAI」を友達追加してください。"""

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=message)]
            )
        )


def handle_group_leave(event):
    """ボットがグループから削除されたときの処理"""
    line_group_id = event.source.group_id
    engine = get_db_engine()
    group_manager = GroupManager(engine)

    print(f"👋 グループ退出イベント: line_group_id={line_group_id}")

    group = group_manager.get_group_by_line_id(line_group_id)
    if group:
        group_manager.delete_group(group['id'])
        print(f"✅ グループ削除完了: group_id={group['id']}")


def handle_member_joined(event):
    """メンバーがグループに参加したときの処理"""
    line_group_id = event.source.group_id
    engine = get_db_engine()
    group_manager = GroupManager(engine)

    group = group_manager.get_group_by_line_id(line_group_id)
    if not group:
        return

    for member in event.joined.members:
        if member.type == 'user':
            group_manager.add_member(group['id'], member.user_id, display_name=None)
            print(f"✅ メンバー追加: user_id={member.user_id}")


def handle_member_left(event):
    """メンバーがグループから退出したときの処理"""
    line_group_id = event.source.group_id
    engine = get_db_engine()
    group_manager = GroupManager(engine)

    group = group_manager.get_group_by_line_id(line_group_id)
    if not group:
        return

    for member in event.left.members:
        if member.type == 'user':
            group_manager.remove_member(group['id'], member.user_id)
            print(f"✅ メンバー削除: user_id={member.user_id}")
'''

print("グループハンドラーコードを生成しました")
print("次のステップ: このコードをmain.pyの末尾に手動で追加してください")
