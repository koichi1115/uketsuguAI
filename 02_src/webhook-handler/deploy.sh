#!/bin/bash

# Cloud Functions デプロイスクリプト

# 環境変数読み込み
PROJECT_ID="uketsuguai-dev"
REGION="asia-northeast1"
FUNCTION_NAME="webhook-handler"

echo "Deploying Cloud Function: ${FUNCTION_NAME}"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"

gcloud functions deploy ${FUNCTION_NAME} \
  --gen2 \
  --runtime=python312 \
  --region=${REGION} \
  --source=. \
  --entry-point=webhook \
  --trigger-http \
  --allow-unauthenticated \
  --env-vars-file=.env.yaml \
  --service-account=webhook-handler@${PROJECT_ID}.iam.gserviceaccount.com \
  --memory=256Mi \
  --timeout=60s \
  --max-instances=10

echo "Deployment completed!"
echo "Function URL:"
gcloud functions describe ${FUNCTION_NAME} --region=${REGION} --gen2 --format='value(serviceConfig.uri)'
