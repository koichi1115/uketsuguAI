"""
タスクサービスモジュール
タスク生成キュー投入と管理
"""
import json
from google.cloud import tasks_v2
from core.config import PROJECT_ID, REGION


def enqueue_task_generation(user_id: str, line_user_id: str):
    """
    Cloud Tasksにタスク生成ジョブを投入

    Args:
        user_id: データベースのユーザーID（UUID）
        line_user_id: LINEユーザーID（Push通知用）
    """
    client = tasks_v2.CloudTasksClient()

    # Cloud Tasksのキュー名
    queue_name = 'task-generation-queue'
    parent = client.queue_path(PROJECT_ID, REGION, queue_name)

    # ワーカーのURL（同じCloud Functionとしてデプロイ）
    worker_url = f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net/task-generator-worker"

    # タスクペイロード（両方のIDを渡す）
    payload = json.dumps({
        'user_id': str(user_id),
        'line_user_id': line_user_id
    }).encode()

    # Cloud Taskを作成（OIDC認証トークン付き）
    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': worker_url,
            'headers': {'Content-Type': 'application/json'},
            'body': payload,
            'oidc_token': {
                'service_account_email': 'webhook-handler@uketsuguai-dev.iam.gserviceaccount.com'
            }
        }
    }

    # タスクをキューに追加
    response = client.create_task(request={'parent': parent, 'task': task})
    print(f"📤 Cloud Taskを投入しました: {response.name}")


def enqueue_personalized_task_generation(user_id: str, line_user_id: str):
    """
    Cloud Tasksに個別タスク生成ジョブを投入

    Args:
        user_id: データベースのユーザーID（UUID）
        line_user_id: LINEユーザーID（Push通知用）
    """
    client = tasks_v2.CloudTasksClient()
    queue_name = 'task-generation-queue'
    parent = client.queue_path(PROJECT_ID, REGION, queue_name)

    worker_url = f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net/personalized-tasks-worker"

    payload = json.dumps({
        'user_id': str(user_id),
        'line_user_id': line_user_id
    }).encode()

    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': worker_url,
            'headers': {'Content-Type': 'application/json'},
            'body': payload,
            'oidc_token': {
                'service_account_email': 'webhook-handler@uketsuguai-dev.iam.gserviceaccount.com'
            }
        }
    }

    response = client.create_task(request={'parent': parent, 'task': task})
    print(f"📤 個別タスク生成ジョブを投入: {response.name}")


def enqueue_tips_enhancement(user_id: str, line_user_id: str):
    """
    Cloud TasksにTips収集ジョブを投入

    Args:
        user_id: データベースのユーザーID（UUID）
        line_user_id: LINEユーザーID（Push通知用）
    """
    client = tasks_v2.CloudTasksClient()
    queue_name = 'task-generation-queue'
    parent = client.queue_path(PROJECT_ID, REGION, queue_name)

    worker_url = f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net/tips-enhancement-worker"

    payload = json.dumps({
        'user_id': str(user_id),
        'line_user_id': line_user_id
    }).encode()

    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': worker_url,
            'headers': {'Content-Type': 'application/json'},
            'body': payload,
            'oidc_token': {
                'service_account_email': 'webhook-handler@uketsuguai-dev.iam.gserviceaccount.com'
            }
        }
    }

    response = client.create_task(request={'parent': parent, 'task': task})
    print(f"📤 Tips収集ジョブを投入: {response.name}")
