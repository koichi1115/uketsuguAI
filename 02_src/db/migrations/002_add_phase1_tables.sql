-- Phase 1: Stripe課金システム & レート制限機能
-- Migration: 002_add_phase1_tables.sql
-- Date: 2025-10-15

-- rate_limits テーブル (レート制限管理)
CREATE TABLE rate_limits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    limit_date DATE NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, limit_date)
);

CREATE INDEX idx_rate_limits_user_date ON rate_limits(user_id, limit_date);
CREATE INDEX idx_rate_limits_date ON rate_limits(limit_date);

CREATE TRIGGER update_rate_limits_updated_at BEFORE UPDATE ON rate_limits
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- tasksテーブルにsource_type列を追加 (AI生成 vs 手動作成の区別)
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_type VARCHAR(20) NOT NULL DEFAULT 'ai_generated';
CREATE INDEX IF NOT EXISTS idx_tasks_source_type ON tasks(source_type) WHERE is_deleted = false;

-- 定期削除処理用のコメント
COMMENT ON TABLE rate_limits IS 'ユーザーごとのメッセージポスト制限を管理。前日以前のレコードは定期削除（保持期間: 7日間）';
COMMENT ON COLUMN rate_limits.limit_date IS '制限対象日（YYYY-MM-DD）';
COMMENT ON COLUMN rate_limits.message_count IS 'メッセージ送信回数。100を超えた場合、制限メッセージを返す';
