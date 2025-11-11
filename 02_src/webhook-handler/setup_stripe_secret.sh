#!/bin/bash

# Stripe APIキーをSecret Managerに追加するスクリプト
# Phase 1: 課金システム実装

# プロジェクトID
PROJECT_ID="uketsuguai-dev"

# Stripe APIキーを環境変数から読み込む
# 使用方法: export STRIPE_API_KEY="sk_test_..."
#          bash setup_stripe_secret.sh

if [ -z "$STRIPE_API_KEY" ]; then
    echo "エラー: STRIPE_API_KEY環境変数が設定されていません"
    echo ""
    echo "使用方法:"
    echo "1. Stripeダッシュボードからテスト用APIキーを取得"
    echo "   https://dashboard.stripe.com/test/apikeys"
    echo ""
    echo "2. 環境変数に設定"
    echo "   export STRIPE_API_KEY=\"sk_test_...\""
    echo ""
    echo "3. このスクリプトを実行"
    echo "   bash setup_stripe_secret.sh"
    exit 1
fi

echo "🔐 Stripe APIキーをSecret Managerに追加します..."

# シークレットを作成
echo "$STRIPE_API_KEY" | gcloud secrets create STRIPE_API_KEY \
    --project="$PROJECT_ID" \
    --replication-policy="automatic" \
    --data-file=-

if [ $? -eq 0 ]; then
    echo "✅ Secret STRIPE_API_KEY が作成されました"

    # Cloud Functionsのサービスアカウントにアクセス権限を付与
    SERVICE_ACCOUNT="webhook-handler@${PROJECT_ID}.iam.gserviceaccount.com"

    gcloud secrets add-iam-policy-binding STRIPE_API_KEY \
        --project="$PROJECT_ID" \
        --member="serviceAccount:$SERVICE_ACCOUNT" \
        --role="roles/secretmanager.secretAccessor"

    echo "✅ サービスアカウントにアクセス権限を付与しました"
else
    echo "❌ Secretの作成に失敗しました"
    exit 1
fi

echo ""
echo "✅ セットアップ完了！"
