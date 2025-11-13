-- Pay It Forward（恩送り）機能のためのテーブル定義

-- 恩送り支払い記録テーブル
CREATE TABLE IF NOT EXISTS pay_it_forward_payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL, -- 支払い金額（円）
    message TEXT, -- 次のユーザーへのメッセージ（最大200文字、任意）
    payment_method VARCHAR(50), -- 支払い方法（stripe, other）
    stripe_payment_intent_id VARCHAR(255), -- Stripe Payment Intent ID
    status VARCHAR(50) NOT NULL DEFAULT 'completed', -- completed, pending, failed
    is_anonymous BOOLEAN NOT NULL DEFAULT true, -- 匿名表示フラグ
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_message_length CHECK (message IS NULL OR LENGTH(message) <= 200)
);

-- 恩送り統計テーブル
CREATE TABLE IF NOT EXISTS pay_it_forward_stats (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    total_payments_count INTEGER NOT NULL DEFAULT 0, -- 累計恩送り人数
    total_amount INTEGER NOT NULL DEFAULT 0, -- 累計金額
    available_pool_count INTEGER NOT NULL DEFAULT 0, -- 現在の恩送りプール人数
    new_users_count INTEGER NOT NULL DEFAULT 0, -- 累計新規ユーザー数
    last_payment_at TIMESTAMP, -- 最後の恩送り日時
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 恩送りメッセージ表示履歴テーブル
CREATE TABLE IF NOT EXISTS pay_it_forward_message_views (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    payment_id UUID NOT NULL REFERENCES pay_it_forward_payments(id) ON DELETE CASCADE,
    viewed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_user_message_view UNIQUE (user_id, payment_id)
);

-- インデックス作成
CREATE INDEX idx_pif_payments_user_id ON pay_it_forward_payments(user_id);
CREATE INDEX idx_pif_payments_created_at ON pay_it_forward_payments(created_at DESC);
CREATE INDEX idx_pif_payments_status ON pay_it_forward_payments(status) WHERE status = 'completed';
CREATE INDEX idx_pif_message_views_user_id ON pay_it_forward_message_views(user_id);

-- 統計レコードの初期化（存在しない場合のみ）
INSERT INTO pay_it_forward_stats (id, total_payments_count, total_amount, available_pool_count, new_users_count)
SELECT uuid_generate_v4(), 0, 0, 0,
       (SELECT COUNT(*) FROM users WHERE is_deleted = false)
WHERE NOT EXISTS (SELECT 1 FROM pay_it_forward_stats);

-- 統計更新用の関数
CREATE OR REPLACE FUNCTION update_pay_it_forward_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.status = 'completed' THEN
        UPDATE pay_it_forward_stats
        SET
            total_payments_count = total_payments_count + 1,
            total_amount = total_amount + NEW.amount,
            available_pool_count = available_pool_count + 1,
            last_payment_at = NEW.created_at,
            updated_at = CURRENT_TIMESTAMP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- トリガー作成
DROP TRIGGER IF EXISTS trigger_update_pif_stats ON pay_it_forward_payments;
CREATE TRIGGER trigger_update_pif_stats
AFTER INSERT ON pay_it_forward_payments
FOR EACH ROW
EXECUTE FUNCTION update_pay_it_forward_stats();

-- 新規ユーザー数更新用の関数
CREATE OR REPLACE FUNCTION update_new_users_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE pay_it_forward_stats
        SET
            new_users_count = new_users_count + 1,
            updated_at = CURRENT_TIMESTAMP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- トリガー作成
DROP TRIGGER IF EXISTS trigger_update_new_users ON users;
CREATE TRIGGER trigger_update_new_users
AFTER INSERT ON users
FOR EACH ROW
EXECUTE FUNCTION update_new_users_count();

-- コメント追加
COMMENT ON TABLE pay_it_forward_payments IS '恩送り支払い記録';
COMMENT ON TABLE pay_it_forward_stats IS '恩送り統計情報';
COMMENT ON TABLE pay_it_forward_message_views IS 'ユーザーが閲覧した恩送りメッセージの履歴';
COMMENT ON COLUMN pay_it_forward_payments.message IS '次のユーザーへのメッセージ（最大200文字、任意）';
COMMENT ON COLUMN pay_it_forward_stats.available_pool_count IS '現在利用可能な恩送りプール人数（支払い済み - 新規ユーザー）';
