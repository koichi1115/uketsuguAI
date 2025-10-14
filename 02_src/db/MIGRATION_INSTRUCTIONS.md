# データベースマイグレーション手順

Phase 1機能（Stripe課金・レート制限）のデータベースマイグレーションを実行します。

## 方法1: GCPコンソールから実行（推奨）

1. **Cloud SQLインスタンスページを開く**
   ```
   https://console.cloud.google.com/sql/instances/uketsuguai-db-dev/overview?project=uketsuguai-dev
   ```

2. **「データベース」タブを選択**

3. **`uketsuguai_db`をクリック**

4. **「SQLエディタ」を開く**

5. **以下のSQLを実行**
   ```sql
   -- Phase 1: Stripe課金システム & レート制限機能
   -- Migration: 002_add_phase1_tables.sql

   -- rate_limits テーブル (レート制限管理)
   CREATE TABLE IF NOT EXISTS rate_limits (
       id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
       user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
       limit_date DATE NOT NULL,
       message_count INTEGER NOT NULL DEFAULT 0,
       created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
       updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
       UNIQUE(user_id, limit_date)
   );

   CREATE INDEX IF NOT EXISTS idx_rate_limits_user_date ON rate_limits(user_id, limit_date);
   CREATE INDEX IF NOT EXISTS idx_rate_limits_date ON rate_limits(limit_date);

   CREATE TRIGGER update_rate_limits_updated_at BEFORE UPDATE ON rate_limits
   FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

   -- tasksテーブルにsource_type列を追加 (AI生成 vs 手動作成の区別)
   ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_type VARCHAR(20) NOT NULL DEFAULT 'ai_generated';
   CREATE INDEX IF NOT EXISTS idx_tasks_source_type ON tasks(source_type) WHERE is_deleted = false;

   -- コメント追加
   COMMENT ON TABLE rate_limits IS 'ユーザーごとのメッセージポスト制限を管理。前日以前のレコードは定期削除（保持期間: 7日間）';
   COMMENT ON COLUMN rate_limits.limit_date IS '制限対象日（YYYY-MM-DD）';
   COMMENT ON COLUMN rate_limits.message_count IS 'メッセージ送信回数。100を超えた場合、制限メッセージを返す';
   ```

6. **「実行」をクリック**

7. **確認**
   ```sql
   -- rate_limitsテーブルが作成されたか確認
   SELECT table_name FROM information_schema.tables
   WHERE table_schema = 'public' AND table_name = 'rate_limits';

   -- tasksテーブルのカラムを確認
   SELECT column_name, data_type, is_nullable, column_default
   FROM information_schema.columns
   WHERE table_name = 'tasks' AND column_name = 'source_type';
   ```

## 方法2: Cloud SQL Proxyを使用（ローカル）

### 前提条件
- Cloud SQL Proxyがインストール済み
- PostgreSQLクライアント（psql）がインストール済み
- DBパスワードを取得済み

### 手順

1. **Cloud SQL Proxyを起動**
   ```bash
   cloud-sql-proxy --port 5432 uketsuguai-dev:asia-northeast1:uketsuguai-db-dev
   ```

2. **別のターミナルでマイグレーション実行**
   ```bash
   cd C:\Users\Administrator\uketsuguAI\02_src\db\migrations

   psql -h 127.0.0.1 -p 5432 -U postgres -d uketsuguai_db -f 002_add_phase1_tables.sql
   ```

3. **パスワード入力**
   - Secret Managerから`DB_PASSWORD`を取得して入力

## 方法3: gcloud CLIを使用

```bash
gcloud sql connect uketsuguai-db-dev --user=postgres --project=uketsuguai-dev --database=uketsuguai_db < 002_add_phase1_tables.sql
```

## マイグレーション後の確認

以下のSQLで正しくマイグレーションされたか確認してください：

```sql
-- テーブル一覧
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;

-- rate_limitsテーブルの構造
\d rate_limits

-- tasksテーブルの構造（source_typeカラムが追加されているか）
\d tasks
```

## トラブルシューティング

### エラー: 「relation "rate_limits" already exists」
→ すでにマイグレーション済みです。問題ありません。

### エラー: 「column "source_type" of relation "tasks" already exists」
→ すでにカラムが追加されています。問題ありません。

### IPv6エラー
→ Cloud SQL Proxyを使用してください（方法2）
