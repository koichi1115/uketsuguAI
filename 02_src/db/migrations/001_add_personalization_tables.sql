-- マイグレーション: タスクパーソナライゼーション機能追加
-- 作成日: 2025-10-13
-- 説明: 追加質問機能とタスク生成ステップ管理機能を追加

-- user_profilesテーブルに追加カラムを追加
ALTER TABLE user_profiles
ADD COLUMN IF NOT EXISTS has_care_insurance BOOLEAN,
ADD COLUMN IF NOT EXISTS has_real_estate BOOLEAN,
ADD COLUMN IF NOT EXISTS has_vehicle BOOLEAN,
ADD COLUMN IF NOT EXISTS has_life_insurance BOOLEAN,
ADD COLUMN IF NOT EXISTS has_children BOOLEAN,
ADD COLUMN IF NOT EXISTS is_self_employed BOOLEAN,
ADD COLUMN IF NOT EXISTS is_dependent_family BOOLEAN,
ADD COLUMN IF NOT EXISTS has_pension BOOLEAN;

-- コメント追加
COMMENT ON COLUMN user_profiles.has_care_insurance IS '介護保険サービスを利用していたか';
COMMENT ON COLUMN user_profiles.has_real_estate IS '不動産を保有しているか';
COMMENT ON COLUMN user_profiles.has_vehicle IS '車両を保有しているか';
COMMENT ON COLUMN user_profiles.has_life_insurance IS '生命保険に加入していたか';
COMMENT ON COLUMN user_profiles.has_children IS '子供がいるか';
COMMENT ON COLUMN user_profiles.is_self_employed IS '自営業だったか';
COMMENT ON COLUMN user_profiles.is_dependent_family IS '扶養家族がいたか';
COMMENT ON COLUMN user_profiles.has_pension IS '年金を受給していたか';

-- 追加質問管理テーブル
CREATE TABLE IF NOT EXISTS follow_up_questions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    question_type VARCHAR(50) NOT NULL DEFAULT 'yes_no',
    question_key VARCHAR(100) NOT NULL,
    options JSONB,
    is_answered BOOLEAN NOT NULL DEFAULT false,
    answer TEXT,
    answered_at TIMESTAMP,
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_follow_up_questions_user_id ON follow_up_questions(user_id);
CREATE INDEX IF NOT EXISTS idx_follow_up_questions_is_answered ON follow_up_questions(user_id, is_answered);
CREATE INDEX IF NOT EXISTS idx_follow_up_questions_display_order ON follow_up_questions(user_id, display_order);

CREATE TRIGGER update_follow_up_questions_updated_at BEFORE UPDATE ON follow_up_questions
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE follow_up_questions IS 'ユーザーへの追加質問を管理';
COMMENT ON COLUMN follow_up_questions.question_type IS 'yes_no, multiple_choice, free_text';
COMMENT ON COLUMN follow_up_questions.question_key IS 'プログラムで参照するためのキー（例: has_care_insurance）';
COMMENT ON COLUMN follow_up_questions.options IS '選択肢（multiple_choiceの場合）';

-- タスク生成ステップ管理テーブル
CREATE TABLE IF NOT EXISTS task_generation_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    step_name VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_generation_steps_user_id ON task_generation_steps(user_id);
CREATE INDEX IF NOT EXISTS idx_task_generation_steps_status ON task_generation_steps(user_id, step_name, status);

CREATE TRIGGER update_task_generation_steps_updated_at BEFORE UPDATE ON task_generation_steps
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE task_generation_steps IS 'タスク生成の各ステップ（basic, personalized, enhanced）の進捗管理';
COMMENT ON COLUMN task_generation_steps.step_name IS 'basic, personalized, enhanced';
COMMENT ON COLUMN task_generation_steps.status IS 'pending, in_progress, completed, failed';

-- tasksテーブルに生成ステップカラムを追加
ALTER TABLE tasks
ADD COLUMN IF NOT EXISTS generation_step VARCHAR(50) DEFAULT 'basic',
ADD COLUMN IF NOT EXISTS tips TEXT;

COMMENT ON COLUMN tasks.generation_step IS 'このタスクを生成したステップ（basic, personalized, enhanced）';
COMMENT ON COLUMN tasks.tips IS '実用的なTips・体験談（SNS・ブログから収集）';

CREATE INDEX IF NOT EXISTS idx_tasks_generation_step ON tasks(user_id, generation_step) WHERE is_deleted = false;

-- 会話状態管理テーブル
CREATE TABLE IF NOT EXISTS conversation_states (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    state_name VARCHAR(100) NOT NULL,
    state_data JSONB,
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, state_name)
);

CREATE INDEX IF NOT EXISTS idx_conversation_states_user_id ON conversation_states(user_id);
CREATE INDEX IF NOT EXISTS idx_conversation_states_expires_at ON conversation_states(expires_at);

CREATE TRIGGER update_conversation_states_updated_at BEFORE UPDATE ON conversation_states
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE conversation_states IS 'ユーザーの会話状態を管理（追加質問の回答待ちなど）';
COMMENT ON COLUMN conversation_states.state_name IS '状態名（例: awaiting_follow_up_answers, personalization_in_progress）';
COMMENT ON COLUMN conversation_states.state_data IS '状態に関連するデータ';
COMMENT ON COLUMN conversation_states.expires_at IS '状態の有効期限';
