"""
無料/有料プラン制御ロジック
Phase 1: タスク表示制限とプラン別機能制御
"""
from typing import List, Dict, Any, Optional
from subscription_manager import SubscriptionManager


class PlanController:
    """プラン別の機能制御"""

    # 無料プランで表示可能なタスク数
    FREE_PLAN_TASK_LIMIT = 2

    def __init__(self, subscription_manager: SubscriptionManager):
        """
        Args:
            subscription_manager: SubscriptionManagerインスタンス
        """
        self.subscription_manager = subscription_manager

    def filter_tasks_by_plan(
        self,
        user_id: str,
        tasks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        ユーザーのプランに応じてタスクリストをフィルタリング

        無料プラン: 最初の2タスクのみ表示、3タスク目以降はマスク
        有料プラン: 全タスク表示

        Args:
            user_id: ユーザーのUUID
            tasks: タスクリスト

        Returns:
            フィルタリング後のタスクリスト
        """
        is_premium = self.subscription_manager.is_premium_user(user_id)
        print(f"🎫 プラン確認: user_id={user_id}, is_premium={is_premium}, tasks_count={len(tasks)}")

        if is_premium:
            # 有料プラン: すべて表示
            return tasks

        # 無料プラン: 2タスクのみ表示、残りはマスク
        filtered_tasks = []

        for idx, task in enumerate(tasks):
            if idx < self.FREE_PLAN_TASK_LIMIT:
                # 最初の2タスクはそのまま表示
                filtered_tasks.append(task)
            else:
                # 3タスク目以降はマスク表示
                masked_task = self._mask_task(task)
                filtered_tasks.append(masked_task)

        return filtered_tasks

    def _mask_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        タスク情報をマスク表示用に変換

        Args:
            task: タスク情報

        Returns:
            マスクされたタスク情報
        """
        return {
            **task,
            "title": "🔒 有料プランで閲覧可能",
            "description": "このタスクを見るには有料プランへのアップグレードが必要です",
            "is_masked": True,
            "metadata": {
                "masked": True,
                "upgrade_required": True
            }
        }

    def can_add_custom_task(self, user_id: str) -> bool:
        """
        ユーザーが独自タスクを追加できるかチェック

        無料プラン: 不可
        有料プラン: 可

        Args:
            user_id: ユーザーのUUID

        Returns:
            追加可能ならTrue
        """
        return self.subscription_manager.is_premium_user(user_id)

    def can_edit_task(self, user_id: str, task: Dict[str, Any]) -> bool:
        """
        ユーザーがタスクを編集できるかチェック

        ルール:
        - 有料プランのみ
        - 手動作成タスク(source_type='user_created')のみ編集可能
        - AI生成タスクは編集不可

        Args:
            user_id: ユーザーのUUID
            task: タスク情報

        Returns:
            編集可能ならTrue
        """
        is_premium = self.subscription_manager.is_premium_user(user_id)
        is_user_created = task.get("source_type") == "user_created"

        return is_premium and is_user_created

    def can_delete_task(self, user_id: str, task: Dict[str, Any]) -> bool:
        """
        ユーザーがタスクを削除できるかチェック

        ルール:
        - 有料プランのみ
        - 手動作成タスク(source_type='user_created')のみ削除可能
        - AI生成タスクは削除不可（完了/スキップのみ）

        Args:
            user_id: ユーザーのUUID
            task: タスク情報

        Returns:
            削除可能ならTrue
        """
        is_premium = self.subscription_manager.is_premium_user(user_id)
        is_user_created = task.get("source_type") == "user_created"

        return is_premium and is_user_created

    def can_access_task_details(self, user_id: str, task_index: int) -> bool:
        """
        ユーザーがタスク詳細にアクセスできるかチェック

        無料プラン: 最初の2タスクのみ
        有料プラン: すべてアクセス可能

        Args:
            user_id: ユーザーのUUID
            task_index: タスクのインデックス（0始まり）

        Returns:
            アクセス可能ならTrue
        """
        is_premium = self.subscription_manager.is_premium_user(user_id)

        if is_premium:
            return True

        # 無料プランは最初の2タスクのみアクセス可能
        return task_index < self.FREE_PLAN_TASK_LIMIT

    def can_use_reminders(self, user_id: str) -> bool:
        """
        ユーザーがリマインダー機能を使用できるかチェック

        無料プラン: 不可
        有料プラン: 可

        Args:
            user_id: ユーザーのUUID

        Returns:
            使用可能ならTrue
        """
        return self.subscription_manager.is_premium_user(user_id)

    def get_upgrade_message(self) -> str:
        """
        アップグレードを促すメッセージを取得

        Returns:
            アップグレードメッセージ
        """
        return (
            "この機能は有料プラン限定です。\n\n"
            "有料プランでは以下の機能が利用できます：\n"
            "✅ すべてのタスクを閲覧\n"
            "✅ 独自タスクの追加・編集・削除\n"
            "✅ リマインダー機能\n"
            "✅ グループLINE対応（準備中）\n\n"
            "月額500円でアップグレード →"
        )

    def get_plan_status_message(self, user_id: str) -> str:
        """
        ユーザーの現在のプラン状態を示すメッセージを取得

        Args:
            user_id: ユーザーのUUID

        Returns:
            プラン状態メッセージ
        """
        subscription = self.subscription_manager.get_user_subscription(user_id)

        if not subscription:
            return "現在のプラン: 無料プラン（2タスクまで閲覧可能）"

        plan_type = subscription["plan_type"]
        status = subscription["status"]

        if status == SubscriptionManager.STATUS_ACTIVE:
            if plan_type == SubscriptionManager.PLAN_BETA:
                return "現在のプラン: β版プラン（月額500円）"
            elif plan_type == SubscriptionManager.PLAN_STANDARD:
                return "現在のプラン: 標準プラン"
        elif status == SubscriptionManager.STATUS_CANCELED:
            return "プランがキャンセルされました。無料プラン（2タスクまで閲覧可能）"
        elif status == SubscriptionManager.STATUS_EXPIRED:
            return "プランの有効期限が切れました。無料プラン（2タスクまで閲覧可能）"

        return "現在のプラン: 無料プラン（2タスクまで閲覧可能）"
