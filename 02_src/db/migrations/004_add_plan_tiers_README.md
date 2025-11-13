# マイグレーション004: 3プラン対応

## 概要

段階的価格設定（無料/ベーシック/プレミアム）を実装するためのデータベース拡張

## 実行日時

- **作成日**: 2025-10-19
- **実行予定**: ローカル検証後、本番環境へ適用

---

## 🎯 変更内容

### 追加カラム

| カラム名 | 型 | デフォルト | 説明 |
|---------|-----|-----------|------|
| ai_chat_count | INTEGER | 0 | 当月のAIチャット利用回数 |
| ai_chat_limit | INTEGER | 0 | AIチャット月間上限（-1で無制限） |
| task_generation_count | INTEGER | 0 | タスク生成回数 |
| task_generation_limit | INTEGER | 1 | タスク生成上限 |
| last_reset_at | TIMESTAMP | CURRENT_TIMESTAMP | カウンターリセット日時 |

### プラン定義

| プラン | plan_type | 価格 | ai_chat_limit | group_enabled |
|--------|-----------|------|---------------|---------------|
| 無料 | `free` | ¥0 | 0 | false |
| ベーシック | `basic` | ¥300 | 10 | false |
| プレミアム | `premium` | ¥500 | -1 | true |

---

## 📋 実行手順

### 1. ローカル環境での検証

#### Step 1: Cloud SQL Proxyの起動

```bash
cd C:/Users/Administrator/uketsuguAI
./cloud-sql-proxy uketsuguai-dev:asia-northeast1:uketsuguai-db
```

#### Step 2: PostgreSQLに接続

```bash
psql "host=localhost port=5432 dbname=uketsuguai user=postgres"
```

#### Step 3: マイグレーション実行

```bash
\i 02_src/db/migrations/004_add_plan_tiers.sql
```

#### Step 4: 検証SQL実行

```sql
-- カラムが追加されたことを確認
\d+ subscriptions

-- 既存データの確認
SELECT
    user_id,
    plan_type,
    ai_chat_limit,
    ai_chat_count,
    task_generation_limit,
    group_enabled,
    status
FROM subscriptions
LIMIT 5;
```

---

### 2. 本番環境への適用

#### Step 1: バックアップ取得

```bash
gcloud sql backups create \
  --instance=uketsuguai-db \
  --project=uketsuguai-dev
```

#### Step 2: Cloud Shellで実行

```bash
# Cloud Shellにログイン
gcloud auth login

# Cloud SQL Proxyを起動
cloud_sql_proxy -instances=uketsuguai-dev:asia-northeast1:uketsuguai-db=tcp:5432 &

# PostgreSQLに接続
psql "host=localhost port=5432 dbname=uketsuguai user=postgres"
```

#### Step 3: マイグレーション実行

```bash
# SQLファイルをアップロード（Cloud Shellの場合）
# または、直接SQLを実行

\i 004_add_plan_tiers.sql
```

---

## ✅ 検証SQL

### カラム追加の確認

```sql
SELECT
    column_name,
    data_type,
    column_default,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'subscriptions'
  AND column_name IN (
      'ai_chat_count',
      'ai_chat_limit',
      'task_generation_count',
      'task_generation_limit',
      'last_reset_at'
  )
ORDER BY column_name;
```

### プラン別レコード数の確認

```sql
SELECT
    plan_type,
    COUNT(*) as user_count,
    AVG(ai_chat_limit) as avg_chat_limit,
    SUM(CASE WHEN group_enabled THEN 1 ELSE 0 END) as group_enabled_count
FROM subscriptions
WHERE status = 'active'
GROUP BY plan_type
ORDER BY plan_type;
```

### 既存ユーザーの移行確認

```sql
-- 有料プランユーザーがプレミアムに移行されたか確認
SELECT
    user_id,
    plan_type,
    ai_chat_limit,
    group_enabled,
    status,
    updated_at
FROM subscriptions
WHERE plan_type = 'premium'
ORDER BY updated_at DESC;
```

---

## 🔄 ロールバック手順

万が一問題が発生した場合のロールバックSQL:

```sql
-- カラムの削除
ALTER TABLE subscriptions
DROP COLUMN IF EXISTS ai_chat_count,
DROP COLUMN IF EXISTS ai_chat_limit,
DROP COLUMN IF EXISTS task_generation_count,
DROP COLUMN IF EXISTS task_generation_limit,
DROP COLUMN IF EXISTS last_reset_at;

-- インデックスの削除
DROP INDEX IF EXISTS idx_subscriptions_plan_type;
```

---

## 📝 注意事項

1. **既存ユーザーの扱い**
   - 既存の無料/beta/standardユーザーは自動的にプラン変更されます
   - `beta`/`standard` → `premium`（無制限チャット、グループ機能有効）
   - その他 → `free`（チャット無効、タスク生成1回のみ）

2. **カウンターリセット**
   - 月初に`ai_chat_count`と`task_generation_count`をリセットする処理が必要
   - 別途Cloud Schedulerで実装予定

3. **Stripeとの連携**
   - Stripe Webhookで有料プラン登録時に`plan_type`を更新する処理が必要

---

## 🎯 次のステップ

1. `plan_manager.py`モジュールの作成
2. プラン判定ロジックの実装
3. AIチャット回数制限の実装
4. タスク生成回数制限の実装
5. 月初カウンターリセット処理の実装（Cloud Scheduler）

---

**作成者**: Claude
**最終更新**: 2025-10-19
