# セキュリティ修正レポート

## Issue #23: 脆弱なセッション管理と認証バイパス (深刻度: 高)

### 発見された脆弱性

#### 1. ユーザー所有権検証の欠如

**影響を受けるファイル:**
- `webhook-handler/main.py`
- `webhook-handler/conversation_flow_manager.py`

**問題の詳細:**

Cloud Tasksから呼び出される非同期ワーカーエンドポイントで、HTTPリクエストから直接 `user_id` と `line_user_id` を取得していましたが、これらの関連性を検証していませんでした。

```python
# 修正前（脆弱なコード）
user_id = request_json.get('user_id')
line_user_id = request_json.get('line_user_id')
# 検証なしで使用
```

**攻撃シナリオ:**

攻撃者が以下のような不正なリクエストを送信できる可能性がありました：
- 他のユーザーの `user_id` と自分の `line_user_id` を組み合わせる
- 他のユーザーのプロフィール情報を取得
- 他のユーザーのタスクにアクセス・変更

**影響を受けるエンドポイント:**
1. `/generate-tasks-step1` - 基本タスク生成
2. `/personalized-tasks-worker` - 個別タスク生成
3. `/tips-enhancement-worker` - Tips収集・拡張

---

### 実装した対策

#### 1. 認証ユーティリティモジュールの作成

**新規ファイル:** `auth_utils.py`

以下の機能を提供：

```python
def verify_user_ownership(conn, line_user_id: str, user_id: str) -> bool:
    """
    line_user_id と user_id の関連性をデータベースで検証

    不正なアクセスの場合は AuthorizationError を発生
    """
```

```python
def verify_task_ownership(conn, user_id: str, task_id: str) -> bool:
    """
    タスクの所有権を検証
    """
```

```python
def verify_profile_ownership(conn, user_id: str, profile_id: Optional[str] = None) -> bool:
    """
    プロフィールの所有権を検証
    """
```

#### 2. 全Cloud Tasksエンドポイントへの検証追加

**修正内容:**

すべての非同期ワーカーエンドポイントに、ユーザー所有権検証を追加：

```python
# 修正後（セキュアなコード）
user_id = request_json.get('user_id')
line_user_id = request_json.get('line_user_id')

engine = get_db_engine()

# ユーザー所有権検証
with engine.connect() as conn:
    try:
        verify_user_ownership(conn, line_user_id, user_id)
    except AuthorizationError as e:
        print(f"❌ 認可エラー: {e}")
        return jsonify({"error": "Unauthorized access"}), 403
```

**修正したエンドポイント:**
1. `generate_tasks_worker` (main.py:287-292行目)
2. `personalized_tasks_worker` (main.py:2221-2227行目)
3. `tips_enhancement_worker` (main.py:2333-2339行目)

---

### セキュリティ強化の詳細

#### 実装された防御メカニズム:

1. **データベースレベルでの検証**
   - `line_user_id` と `user_id` の関連性をJOINで確認
   - SQLインジェクション対策（パラメータ化クエリ使用）

2. **早期検証**
   - エンドポイント処理の最初にユーザー検証を実行
   - 不正なアクセスは即座に403エラーで拒否

3. **詳細なログ記録**
   - 認可エラーをログに記録
   - セキュリティ監査に活用可能

4. **型安全性**
   - カスタム例外 `AuthorizationError` で明確なエラーハンドリング

---

### 追加の推奨事項

#### 1. Cloud Tasks認証の強化

現在の実装では、Cloud Tasksのエンドポイントに対する追加の認証は実装していません。以下の対策を推奨：

```python
# Cloud Tasks専用の認証トークン検証を追加
def verify_cloud_tasks_request(request):
    """Cloud Tasksからのリクエストであることを検証"""
    # OIDC トークン検証
    # または、Cloud Tasks専用のシークレットトークン検証
```

#### 2. レート制限

不正なアクセス試行を防ぐため、レート制限の実装を推奨：
- 同一 `line_user_id` からの連続リクエストを制限
- 失敗した認証試行の記録

#### 3. 監査ログ

セキュリティイベントの詳細な記録：
- すべての認可失敗をログに記録
- 定期的な監査レポートの生成

---

### テスト推奨項目

1. **正常系テスト**
   - 正しい `user_id` と `line_user_id` でアクセス成功

2. **異常系テスト**
   - 不正な `user_id` と `line_user_id` の組み合わせで403エラー
   - 存在しない `user_id` で403エラー
   - 存在しない `line_user_id` で403エラー

3. **セキュリティテスト**
   - 他のユーザーのデータへの不正アクセス試行
   - SQLインジェクション攻撃の防御確認

---

### 修正履歴

| 日付 | 修正内容 | 担当者 |
|------|---------|--------|
| 2025-11-05 | Issue #23対応: ユーザー所有権検証の実装 | Claude Code |

---

### 参考資料

- GitHub Issue: #23
- OWASP Top 10 - Broken Access Control
- CWE-639: Authorization Bypass Through User-Controlled Key
