-- マイグレーション: サービス選択機能追加（LLMパーソナライズ強化）
-- 作成日: 2025-11-21
-- 説明: 保険会社・銀行・携帯キャリア等の具体的なサービス選択機能

-- ユーザーが選択したサービスを保存するテーブル
CREATE TABLE IF NOT EXISTS user_services (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    service_type VARCHAR(50) NOT NULL,
    service_name VARCHAR(200) NOT NULL,
    custom_name VARCHAR(200),
    metadata JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_services_user_id ON user_services(user_id);
CREATE INDEX IF NOT EXISTS idx_user_services_type ON user_services(user_id, service_type);

CREATE TRIGGER update_user_services_updated_at BEFORE UPDATE ON user_services
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE user_services IS 'ユーザーが選択した具体的なサービス（保険会社、銀行等）';
COMMENT ON COLUMN user_services.service_type IS 'サービス種別（life_insurance, bank, credit_card, mobile_carrier, subscription, utility）';
COMMENT ON COLUMN user_services.service_name IS 'サービス名（日本生命、三菱UFJ銀行等）または「その他」';
COMMENT ON COLUMN user_services.custom_name IS 'その他を選択した場合の自由入力名';
COMMENT ON COLUMN user_services.metadata IS '追加情報（証券番号有無、口座種別等）';

-- user_profilesに追加カラム（銀行・クレカ・携帯等の有無フラグ）
ALTER TABLE user_profiles
ADD COLUMN IF NOT EXISTS has_bank_account BOOLEAN,
ADD COLUMN IF NOT EXISTS has_credit_card BOOLEAN,
ADD COLUMN IF NOT EXISTS has_mobile_contract BOOLEAN,
ADD COLUMN IF NOT EXISTS has_subscription BOOLEAN;

COMMENT ON COLUMN user_profiles.has_bank_account IS '銀行口座を保有しているか';
COMMENT ON COLUMN user_profiles.has_credit_card IS 'クレジットカードを保有しているか';
COMMENT ON COLUMN user_profiles.has_mobile_contract IS '携帯電話契約があるか';
COMMENT ON COLUMN user_profiles.has_subscription IS 'サブスクリプション契約があるか';

-- follow_up_questionsにparent_question_key追加（連動質問用）
ALTER TABLE follow_up_questions
ADD COLUMN IF NOT EXISTS parent_question_key VARCHAR(100),
ADD COLUMN IF NOT EXISTS trigger_answer VARCHAR(50);

COMMENT ON COLUMN follow_up_questions.parent_question_key IS '親質問のkey（連動質問用）';
COMMENT ON COLUMN follow_up_questions.trigger_answer IS 'この質問が表示される親質問の回答（例: はい）';
