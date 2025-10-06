# Webhook Handler

LINEからのWebhookを受け取り、ユーザーメッセージを処理するCloud Functions。

## 機能

- LINE友だち追加時のウェルカムメッセージ送信
- ユーザー情報のDB登録
- メッセージ受信と会話履歴の保存
- ポストバックイベント処理

## デプロイ前の準備

### 1. サービスアカウント作成

```bash
# サービスアカウント作成
gcloud iam service-accounts create webhook-handler \
  --display-name="Webhook Handler Service Account" \
  --project=uketsuguai-dev

# 必要な権限を付与
gcloud projects add-iam-policy-binding uketsuguai-dev \
  --member="serviceAccount:webhook-handler@uketsuguai-dev.iam.gserviceaccount.com" \
  --role="roles/cloudsql.client"

gcloud projects add-iam-policy-binding uketsuguai-dev \
  --member="serviceAccount:webhook-handler@uketsuguai-dev.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 2. Secret Manager にシークレット登録済み確認

以下のシークレットが登録されていることを確認:
- LINE_CHANNEL_SECRET
- LINE_CHANNEL_ACCESS_TOKEN
- DB_CONNECTION_NAME
- DB_USER
- DB_PASSWORD
- DB_NAME

## デプロイ

```bash
# デプロイスクリプトに実行権限を付与
chmod +x deploy.sh

# デプロイ実行
./deploy.sh
```

## デプロイ後の設定

### 1. Webhook URL をLINEに登録

デプロイ完了後に表示されるFunction URLをコピーして、LINE Developers コンソールで設定:

1. LINE Developers (https://developers.line.biz/console/) にアクセス
2. Messaging API チャネルを選択
3. Messaging API設定 → Webhook settings
4. Webhook URL に Function URL を設定
5. 「検証」をクリックして接続確認
6. 「Webhookの利用」を ON にする

### 2. 動作確認

LINEアプリで公式アカウントを友だち追加し、ウェルカムメッセージが届くことを確認

## ローカル開発

```bash
# 仮想環境作成
python3 -m venv venv
source venv/bin/activate

# 依存パッケージインストール
pip install -r requirements.txt

# Functions Framework で起動
functions-framework --target=webhook --debug
```

## トラブルシューティング

### デプロイエラー

```bash
# ログ確認
gcloud functions logs read webhook-handler --region=asia-northeast1 --gen2 --limit=50
```

### データベース接続エラー

- Cloud SQL への接続権限があるか確認
- DB_CONNECTION_NAME の形式が正しいか確認（`project:region:instance`）
