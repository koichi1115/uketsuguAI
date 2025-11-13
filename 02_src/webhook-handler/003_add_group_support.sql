-- Migration: グループLINE対応
-- Phase 2: グループチャット機能の追加

-- groups テーブル: グループチャット情報を管理
CREATE TABLE IF NOT EXISTS groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    line_group_id VARCHAR(255) NOT NULL UNIQUE,
    owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_name VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_groups_line_group_id ON groups(line_group_id);
CREATE INDEX idx_groups_owner_user_id ON groups(owner_user_id) WHERE is_deleted = false;
CREATE INDEX idx_groups_status ON groups(status) WHERE is_deleted = false;

CREATE TRIGGER update_groups_updated_at BEFORE UPDATE ON groups
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE groups IS 'グループチャット情報';
COMMENT ON COLUMN groups.line_group_id IS 'LINE Group ID（一意）';
COMMENT ON COLUMN groups.owner_user_id IS 'マスタアカウントのuser_id';
COMMENT ON COLUMN groups.group_name IS 'グループ名';
COMMENT ON COLUMN groups.status IS 'ステータス（active, inactive）';

-- group_members テーブル: グループメンバー情報を管理
CREATE TABLE IF NOT EXISTS group_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    line_user_id VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT true,
    joined_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    left_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_group_members_group_id ON group_members(group_id) WHERE is_active = true;
CREATE INDEX idx_group_members_line_user_id ON group_members(line_user_id);
CREATE INDEX idx_group_members_group_user ON group_members(group_id, line_user_id);

CREATE TRIGGER update_group_members_updated_at BEFORE UPDATE ON group_members
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE group_members IS 'グループメンバー情報';
COMMENT ON COLUMN group_members.line_user_id IS 'メンバーのLINE User ID';
COMMENT ON COLUMN group_members.display_name IS 'メンバーの表示名';
COMMENT ON COLUMN group_members.is_active IS 'グループに在籍中か';

-- tasks テーブルに group_id と assigned_to を追加
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS group_id UUID REFERENCES groups(id) ON DELETE CASCADE;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assigned_to_line_user_id VARCHAR(255);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assigned_to_display_name VARCHAR(255);

CREATE INDEX idx_tasks_group_id ON tasks(group_id) WHERE is_deleted = false;
CREATE INDEX idx_tasks_assigned_to ON tasks(assigned_to_line_user_id) WHERE is_deleted = false;

COMMENT ON COLUMN tasks.group_id IS 'グループタスクの場合はgroup_id、個人タスクの場合はNULL';
COMMENT ON COLUMN tasks.assigned_to_line_user_id IS 'タスク担当者のLINE User ID';
COMMENT ON COLUMN tasks.assigned_to_display_name IS 'タスク担当者の表示名';

-- subscriptions テーブルに group_enabled フラグを追加
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS group_enabled BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN subscriptions.group_enabled IS '有料プランでグループチャット機能が有効か';
