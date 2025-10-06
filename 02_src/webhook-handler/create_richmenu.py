"""
リッチメニュー作成スクリプト
LINE Bot用のリッチメニューを作成・設定する
"""

import os
import requests
import json
from PIL import Image
import io

# アクセストークンを取得
def get_access_token() -> str:
    """環境変数またはSecret Managerからアクセストークンを取得"""
    # まず環境変数を確認
    token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    if token:
        return token

    # なければSecret Managerから取得
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        project_id = "uketsuguai-dev"
        name = f"projects/{project_id}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except ImportError:
        print("❌ エラー: LINE_CHANNEL_ACCESS_TOKEN環境変数を設定してください")
        print("   PowerShell: $env:LINE_CHANNEL_ACCESS_TOKEN='your_token'")
        exit(1)


def create_richmenu():
    """リッチメニューを作成"""
    channel_access_token = get_access_token()

    # リッチメニューの設定（2x3レイアウト）
    richmenu_data = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "受け継ぐAI メインメニュー",
        "chatBarText": "メニュー",
        "areas": [
            # 右上: タスク一覧
            {
                "bounds": {
                    "x": 1667,
                    "y": 0,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "label": "タスク一覧",
                    "text": "タスク"
                }
            },
            # 左下: AI相談
            {
                "bounds": {
                    "x": 0,
                    "y": 843,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "label": "AI相談",
                    "text": "相談したいことがあります"
                }
            },
            # 中央下: 設定
            {
                "bounds": {
                    "x": 833,
                    "y": 843,
                    "width": 834,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "label": "設定",
                    "text": "設定"
                }
            },
            # 右下: ヘルプ
            {
                "bounds": {
                    "x": 1667,
                    "y": 843,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "label": "ヘルプ",
                    "text": "ヘルプ"
                }
            }
        ]
    }

    # リッチメニュー作成API
    headers = {
        "Authorization": f"Bearer {channel_access_token}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        "https://api.line.me/v2/bot/richmenu",
        headers=headers,
        data=json.dumps(richmenu_data)
    )

    if response.status_code == 200:
        richmenu_id = response.json()["richMenuId"]
        print(f"✅ リッチメニュー作成成功: {richmenu_id}")
        return richmenu_id
    else:
        print(f"❌ リッチメニュー作成失敗: {response.status_code}")
        print(response.text)
        return None


def compress_image(image_path: str, max_size_mb: float = 0.9) -> bytes:
    """画像を圧縮してバイトデータを返す（最大サイズ以下に）"""
    img = Image.open(image_path)

    # PNG形式で保存
    quality = 95
    while quality > 20:
        output = io.BytesIO()
        img.save(output, format='PNG', optimize=True)
        size_mb = len(output.getvalue()) / (1024 * 1024)

        if size_mb <= max_size_mb:
            print(f"📦 画像圧縮完了: {size_mb:.2f}MB (品質: {quality})")
            return output.getvalue()

        # JPEG形式に変換して再試行
        output = io.BytesIO()
        rgb_img = img.convert('RGB')
        rgb_img.save(output, format='JPEG', quality=quality, optimize=True)
        size_mb = len(output.getvalue()) / (1024 * 1024)

        if size_mb <= max_size_mb:
            print(f"📦 画像圧縮完了 (JPEG): {size_mb:.2f}MB (品質: {quality})")
            return output.getvalue()

        quality -= 5

    # 最低品質でも大きい場合
    output = io.BytesIO()
    rgb_img = img.convert('RGB')
    rgb_img.save(output, format='JPEG', quality=20, optimize=True)
    print(f"⚠️ 最低品質で圧縮: {len(output.getvalue()) / (1024 * 1024):.2f}MB")
    return output.getvalue()


def upload_richmenu_image(richmenu_id: str, image_path: str):
    """リッチメニュー画像をアップロード"""
    channel_access_token = get_access_token()

    # ファイルサイズを確認
    file_size_mb = os.path.getsize(image_path) / (1024 * 1024)
    print(f"📊 元の画像サイズ: {file_size_mb:.2f}MB")

    # 1MB以上なら圧縮
    if file_size_mb > 1.0:
        print(f"⚙️ 画像を圧縮中...")
        image_data = compress_image(image_path)
        content_type = "image/jpeg"
    else:
        with open(image_path, "rb") as f:
            image_data = f.read()
        content_type = "image/png"

    headers = {
        "Authorization": f"Bearer {channel_access_token}",
        "Content-Type": content_type
    }

    response = requests.post(
        f"https://api-data.line.me/v2/bot/richmenu/{richmenu_id}/content",
        headers=headers,
        data=image_data
    )

    if response.status_code == 200:
        print(f"✅ 画像アップロード成功")
        return True
    else:
        print(f"❌ 画像アップロード失敗: {response.status_code}")
        print(response.text)
        return False


def set_default_richmenu(richmenu_id: str):
    """デフォルトリッチメニューとして設定"""
    channel_access_token = get_access_token()

    headers = {
        "Authorization": f"Bearer {channel_access_token}"
    }

    response = requests.post(
        f"https://api.line.me/v2/bot/user/all/richmenu/{richmenu_id}",
        headers=headers
    )

    if response.status_code == 200:
        print(f"✅ デフォルトリッチメニュー設定成功")
        return True
    else:
        print(f"❌ デフォルトリッチメニュー設定失敗: {response.status_code}")
        print(response.text)
        return False


def list_richmenus():
    """既存のリッチメニュー一覧を取得"""
    channel_access_token = get_access_token()

    headers = {
        "Authorization": f"Bearer {channel_access_token}"
    }

    response = requests.get(
        "https://api.line.me/v2/bot/richmenu/list",
        headers=headers
    )

    if response.status_code == 200:
        richmenus = response.json().get("richmenus", [])
        print(f"\n📋 既存のリッチメニュー ({len(richmenus)}件):")
        for rm in richmenus:
            print(f"  - {rm['richMenuId']}: {rm['name']}")
        return richmenus
    else:
        print(f"❌ リッチメニュー取得失敗: {response.status_code}")
        return []


def delete_richmenu(richmenu_id: str):
    """リッチメニューを削除"""
    channel_access_token = get_access_token()

    headers = {
        "Authorization": f"Bearer {channel_access_token}"
    }

    response = requests.delete(
        f"https://api.line.me/v2/bot/richmenu/{richmenu_id}",
        headers=headers
    )

    if response.status_code == 200:
        print(f"✅ リッチメニュー削除成功: {richmenu_id}")
        return True
    else:
        print(f"❌ リッチメニュー削除失敗: {response.status_code}")
        print(response.text)
        return False


if __name__ == "__main__":
    import sys

    print("=== 受け継ぐAI リッチメニュー設定 ===\n")

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        # リッチメニュー一覧表示
        list_richmenus()

    elif len(sys.argv) > 1 and sys.argv[1] == "delete":
        # リッチメニュー削除
        if len(sys.argv) < 3:
            print("使い方: python create_richmenu.py delete <richmenu_id>")
        else:
            delete_richmenu(sys.argv[2])

    elif len(sys.argv) > 1 and sys.argv[1] == "create":
        # リッチメニュー作成
        if len(sys.argv) < 3:
            print("使い方: python create_richmenu.py create <image_path>")
        else:
            print("1. リッチメニューを作成中...")
            richmenu_id = create_richmenu()

            if richmenu_id:
                print(f"\n2. 画像をアップロード中...")
                if upload_richmenu_image(richmenu_id, sys.argv[2]):
                    print(f"\n3. デフォルトリッチメニューとして設定中...")
                    set_default_richmenu(richmenu_id)
                    print(f"\n✅ リッチメニュー設定完了！")

    else:
        print("使い方:")
        print("  python create_richmenu.py list                    # 既存メニュー一覧")
        print("  python create_richmenu.py create <image_path>     # 新規作成")
        print("  python create_richmenu.py delete <richmenu_id>    # 削除")
