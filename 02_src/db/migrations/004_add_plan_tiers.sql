-- Migration: 3プラン対応（無料/ベーシック/プレミアム）
-- Phase 3: 段階的価格設定の実装

-- subscriptions テーブルに利用制限カラムを追加
ALTER TABLE subscriptions
ADD COLUMN IF NOT EXISTS ai_chat_count INTEGER NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS ai_chat_limit INTEGER NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS task_generation_count INTEGER NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS task_generation_limit INTEGER NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS last_reset_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- インデックスの追加
CREATE INDEX IF NOT EXISTS idx_subscriptions_plan_type ON subscriptions(plan_type);

-- カラムコメント
COMMENT ON COLUMN subscriptions.ai_chat_count IS '当月のAIチャット利用回数カウンター';
COMMENT ON COLUMN subscriptions.ai_chat_limit IS 'AIチャット月間上限（-1で無制限、0で利用不可）';
COMMENT ON COLUMN subscriptions.task_generation_count IS 'タスク生成回数カウンター';
COMMENT ON COLUMN subscriptions.task_generation_limit IS 'タスク生成上限';
COMMENT ON COLUMN subscriptions.last_reset_at IS 'カウンターリセット日時（月初にリセット）';

-- 既存レコードの更新（既存ユーザーを無料プランに設定）
UPDATE subscriptions
SET
    plan_type = 'free',
    ai_chat_limit = 0,
    ai_chat_count = 0,
    task_generation_limit = 1,
    task_generation_count = 0,
    group_enabled = false,
    last_reset_at = CURRENT_TIMESTAMP
WHERE plan_type NOT IN ('free', 'basic', 'premium');

-- 既存の有料プランユーザー（betaなど）をプレミアムプランに移行
UPDATE subscriptions
SET
    plan_type = 'premium',
    ai_chat_limit = -1,  -- 無制限
    ai_chat_count = 0,
    task_generation_limit = 1,
    task_generation_count = 0,
    group_enabled = true,
    last_reset_at = CURRENT_TIMESTAMP
WHERE plan_type IN ('beta', 'standard') AND status = 'active';
