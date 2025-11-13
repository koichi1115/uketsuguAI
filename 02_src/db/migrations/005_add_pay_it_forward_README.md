

# Pay It Forward（恩送り）機能 マイグレーション

## 概要
Pay It Forward（恩送り）機能のためのデータベーステーブルを追加します。

## 実行方法

### 1. Cloud SQLに接続
```bash
gcloud sql connect uketsuguai-dev-instance --user=postgres --project=uketsuguai-dev
```

### 2. マイグレーション実行
```sql
\i /path/to/005_add_pay_it_forward.sql
```

または

```bash
psql -h <HOST> -U postgres -d uketsuguai_dev < 005_add_pay_it_forward.sql
```

## テーブル構成

### 1. pay_it_forward_payments
恩送り支払い記録を管理

**主要カラム:**
- `user_id`: 支払いユーザー
- `amount`: 支払い金額（円）
- `message`: 次のユーザーへのメッセージ（最大200文字、任意）
- `status`: completed, pending, failed

### 2. pay_it_forward_stats
恩送り統計情報（サイト全体で1レコード）

**主要カラム:**
- `total_payments_count`: 累計恩送り人数
- `available_pool_count`: 現在の恩送りプール人数
- `new_users_count`: 累計新規ユーザー数

### 3. pay_it_forward_message_views
ユーザーが閲覧した恩送りメッセージの履歴

**主要カラム:**
- `user_id`: 閲覧ユーザー
- `payment_id`: 閲覧したメッセージの支払いID
- `viewed_at`: 閲覧日時

## 自動更新機能

### トリガー
- `trigger_update_pif_stats`: 新しい恩送り支払いがあると統計を自動更新
- `trigger_update_new_users`: 新規ユーザー登録時にカウントを自動更新

### 統計計算ロジック
- **available_pool_count**: 支払い済み人数 - 新規ユーザー数で計算
- **メッセージ表示条件**: `total_payments_count > new_users_count` の場合のみ表示

## ロールバック

```sql
DROP TRIGGER IF EXISTS trigger_update_pif_stats ON pay_it_forward_payments;
DROP TRIGGER IF EXISTS trigger_update_new_users ON users;
DROP FUNCTION IF EXISTS update_pay_it_forward_stats();
DROP FUNCTION IF EXISTS update_new_users_count();
DROP TABLE IF EXISTS pay_it_forward_message_views;
DROP TABLE IF EXISTS pay_it_forward_stats;
DROP TABLE IF EXISTS pay_it_forward_payments;
```

## 初期データ確認

```sql
-- 統計情報確認
SELECT * FROM pay_it_forward_stats;

-- 支払い履歴確認
SELECT id, user_id, amount, LEFT(message, 50) as message_preview, created_at
FROM pay_it_forward_payments
ORDER BY created_at DESC
LIMIT 10;
```
