-- ============================================================
-- フルマイグレーション: タスクパーソナライゼーション機能
-- 作成日: 2025-10-13
-- 説明: 既存データを削除して、パーソナライゼーション機能を追加
-- ============================================================

-- ============================================================
-- Step 1: 既存テーブルのDROP（依存関係順）
-- ============================================================

-- 会話状態管理テーブルを削除
DROP TABLE IF EXISTS conversation_states CASCADE;

-- タスク生成ステップ管理テーブルを削除
DROP TABLE IF EXISTS task_generation_steps CASCADE;

-- 追加質問管理テーブルを削除
DROP TABLE IF EXISTS follow_up_questions CASCADE;

-- タスク進捗テーブルを削除
DROP TABLE IF EXISTS task_progress CASCADE;

-- タスクテーブルを削除
DROP TABLE IF EXISTS tasks CASCADE;

-- ユーザープロフィールテーブルを削除
DROP TABLE IF EXISTS user_profiles CASCADE;

-- 会話履歴テーブルを削除
DROP TABLE IF EXISTS conversation_history CASCADE;

-- ユーザーテーブルを削除
DROP TABLE IF EXISTS users CASCADE;

-- ============================================================
-- Step 2: 基本テーブルの再作成
-- ============================================================

-- uuid-ossp拡張を有効化（UUIDを使用するため）
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- updated_at自動更新関数を作成
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- usersテーブル: ユーザー基本情報
-- ============================================================
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    line_user_id VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    last_login_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_line_user_id ON users(line_user_id);
CREATE INDEX idx_users_status ON users(status);

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE users IS 'LINEユーザー情報';
COMMENT ON COLUMN users.status IS 'active, inactive, deleted';

-- ============================================================
-- user_profilesテーブル: ユーザープロフィール（拡張版）
-- ============================================================
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    relationship VARCHAR(100),
    prefecture VARCHAR(100),
    municipality VARCHAR(100),
    death_date DATE,
    -- パーソナライゼーション用の追加カラム
    has_care_insurance BOOLEAN,
    has_real_estate BOOLEAN,
    has_vehicle BOOLEAN,
    has_life_insurance BOOLEAN,
    has_children BOOLEAN,
    is_self_employed BOOLEAN,
    is_dependent_family BOOLEAN,
    has_pension BOOLEAN,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id)
);

CREATE INDEX idx_user_profiles_user_id ON user_profiles(user_id);

CREATE TRIGGER update_user_profiles_updated_at BEFORE UPDATE ON user_profiles
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE user_profiles IS 'ユーザーのプロフィール情報';
COMMENT ON COLUMN user_profiles.relationship IS '故人との関係';
COMMENT ON COLUMN user_profiles.has_care_insurance IS '介護保険サービスを利用していたか';
COMMENT ON COLUMN user_profiles.has_real_estate IS '不動産を保有しているか';
COMMENT ON COLUMN user_profiles.has_vehicle IS '車両を保有しているか';
COMMENT ON COLUMN user_profiles.has_life_insurance IS '生命保険に加入していたか';
COMMENT ON COLUMN user_profiles.has_children IS '子供がいるか';
COMMENT ON COLUMN user_profiles.is_self_employed IS '自営業だったか';
COMMENT ON COLUMN user_profiles.is_dependent_family IS '扶養家族がいたか';
COMMENT ON COLUMN user_profiles.has_pension IS '年金を受給していたか';

-- ============================================================
-- conversation_historyテーブル: 会話履歴
-- ============================================================
CREATE TABLE conversation_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_conversation_history_user_id ON conversation_history(user_id);
CREATE INDEX idx_conversation_history_created_at ON conversation_history(created_at);

COMMENT ON TABLE conversation_history IS 'ユーザーとAIの会話履歴';
COMMENT ON COLUMN conversation_history.role IS 'user, assistant, system';

-- ============================================================
-- tasksテーブル: タスク情報（拡張版）
-- ============================================================
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    priority VARCHAR(50) DEFAULT 'medium',
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    due_date DATE,
    order_index INTEGER DEFAULT 0,
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    metadata JSONB,
    -- パーソナライゼーション用の追加カラム
    generation_step VARCHAR(50) DEFAULT 'basic',
    tips TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tasks_user_id ON tasks(user_id);
CREATE INDEX idx_tasks_status ON tasks(status) WHERE is_deleted = false;
CREATE INDEX idx_tasks_due_date ON tasks(due_date) WHERE is_deleted = false;
CREATE INDEX idx_tasks_generation_step ON tasks(user_id, generation_step) WHERE is_deleted = false;

CREATE TRIGGER update_tasks_updated_at BEFORE UPDATE ON tasks
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE tasks IS 'ユーザーのタスク情報';
COMMENT ON COLUMN tasks.priority IS 'low, medium, high';
COMMENT ON COLUMN tasks.status IS 'pending, in_progress, completed';
COMMENT ON COLUMN tasks.generation_step IS 'このタスクを生成したステップ（basic, personalized, enhanced）';
COMMENT ON COLUMN tasks.tips IS '実用的なTips・体験談（SNS・ブログから収集）';

-- ============================================================
-- task_progressテーブル: タスク進捗履歴
-- ============================================================
CREATE TABLE task_progress (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_task_progress_task_id ON task_progress(task_id);
CREATE INDEX idx_task_progress_created_at ON task_progress(created_at);

COMMENT ON TABLE task_progress IS 'タスクの進捗履歴';

-- ============================================================
-- Step 3: パーソナライゼーション機能用テーブルの作成
-- ============================================================

-- ============================================================
-- follow_up_questionsテーブル: 追加質問管理
-- ============================================================
CREATE TABLE follow_up_questions (
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

CREATE INDEX idx_follow_up_questions_user_id ON follow_up_questions(user_id);
CREATE INDEX idx_follow_up_questions_is_answered ON follow_up_questions(user_id, is_answered);
CREATE INDEX idx_follow_up_questions_display_order ON follow_up_questions(user_id, display_order);

CREATE TRIGGER update_follow_up_questions_updated_at BEFORE UPDATE ON follow_up_questions
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE follow_up_questions IS 'ユーザーへの追加質問を管理';
COMMENT ON COLUMN follow_up_questions.question_type IS 'yes_no, multiple_choice, free_text';
COMMENT ON COLUMN follow_up_questions.question_key IS 'プログラムで参照するためのキー（例: has_care_insurance）';
COMMENT ON COLUMN follow_up_questions.options IS '選択肢（multiple_choiceの場合）';

-- ============================================================
-- task_generation_stepsテーブル: タスク生成ステップ管理
-- ============================================================
CREATE TABLE task_generation_steps (
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

CREATE INDEX idx_task_generation_steps_user_id ON task_generation_steps(user_id);
CREATE INDEX idx_task_generation_steps_status ON task_generation_steps(user_id, step_name, status);

CREATE TRIGGER update_task_generation_steps_updated_at BEFORE UPDATE ON task_generation_steps
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE task_generation_steps IS 'タスク生成の各ステップ（basic, personalized, enhanced）の進捗管理';
COMMENT ON COLUMN task_generation_steps.step_name IS 'basic, personalized, enhanced';
COMMENT ON COLUMN task_generation_steps.status IS 'pending, in_progress, completed, failed';

-- ============================================================
-- conversation_statesテーブル: 会話状態管理
-- ============================================================
CREATE TABLE conversation_states (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    state_name VARCHAR(100) NOT NULL,
    state_data JSONB,
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, state_name)
);

CREATE INDEX idx_conversation_states_user_id ON conversation_states(user_id);
CREATE INDEX idx_conversation_states_expires_at ON conversation_states(expires_at);

CREATE TRIGGER update_conversation_states_updated_at BEFORE UPDATE ON conversation_states
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE conversation_states IS 'ユーザーの会話状態を管理（追加質問の回答待ちなど）';
COMMENT ON COLUMN conversation_states.state_name IS '状態名（例: awaiting_follow_up_answers, personalization_in_progress）';
COMMENT ON COLUMN conversation_states.state_data IS '状態に関連するデータ';
COMMENT ON COLUMN conversation_states.expires_at IS '状態の有効期限';

-- ============================================================
-- マイグレーション完了
-- ============================================================
