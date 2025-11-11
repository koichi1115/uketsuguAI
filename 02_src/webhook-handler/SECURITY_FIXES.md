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

---

## Issue #22: データベース接続プールの枯渇とリソースリーク (深刻度: 高)

### 発見された脆弱性

#### 1. 接続プール設定の欠如

**問題の詳細:**

SQLAlchemy エンジンが接続プール設定なしで初期化されていました：

```python
# 修正前（脆弱なコード）
_engine = sqlalchemy.create_engine(
    "postgresql+pg8000://",
    creator=get_db_connection,
)
```

**影響:**
- 同時リクエスト時の接続枯渇
- リソースリーク
- DoS攻撃のリスク

#### 2. コンテキストマネージャーの欠如

**影響を受けるファイル:**
- `task_generator_worker.py` (130行目)

**問題の詳細:**

```python
# 修正前（リソースリーク）
tasks = generate_basic_tasks(user_id, profile, engine.connect())
```

---

### 実装した対策

#### 1. 接続プール設定の追加

**修正内容 (main.py:140-149行目):**

```python
# 修正後（セキュアなコード）
_engine = sqlalchemy.create_engine(
    "postgresql+pg8000://",
    creator=get_db_connection,
    pool_size=5,           # 同時接続数の上限
    max_overflow=10,       # pool_sizeを超えた場合の追加接続数
    pool_timeout=30,       # 接続取得のタイムアウト（秒）
    pool_recycle=1800,     # 接続の再利用期限（30分）
    pool_pre_ping=True,    # 接続の有効性を事前確認
)
```

#### 2. コンテキストマネージャーの追加

**修正内容 (task_generator_worker.py:130-131行目):**

```python
# 修正後（適切なリソース管理）
with engine.connect() as conn:
    tasks = generate_basic_tasks(user_id, profile, conn)
```

---

## Issue #21: APIキーの露出とシークレット管理の脆弱性 (深刻度: 高)

### 発見された脆弱性

#### 1. エラーハンドリングの不足

**問題の詳細:**

Secret Manager からのシークレット取得時にエラーハンドリングがなく、機密情報がログに漏洩するリスクがありました。

#### 2. ハードコードされたサービスアカウント

**影響を受ける箇所:**
- main.py (218, 248, 277行目)

**問題の詳細:**

```python
# 修正前（環境依存のハードコード）
'service_account_email': 'webhook-handler@uketsuguai-dev.iam.gserviceaccount.com'
```

---

### 実装した対策

#### 1. Secret Manager エラーハンドリング

**修正内容 (main.py:64-91行目):**

```python
def get_secret(secret_id: str) -> str:
    """Secret Managerからシークレットを取得（エラーハンドリング付き）"""
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")

        # ログにシークレット値を出力しない（セキュリティ対策）
        print(f"✅ シークレット取得成功: {secret_id}")
        return secret_value

    except Exception as e:
        # エラー詳細をログに記録（シークレット値は含めない）
        print(f"❌ シークレット取得エラー: secret_id={secret_id}, error={type(e).__name__}")
        raise Exception(f"Failed to retrieve secret: {secret_id}") from e
```

#### 2. サービスアカウントの環境変数化

**修正内容 (main.py:52-58行目):**

```python
# 環境変数から動的に取得
SERVICE_ACCOUNT_EMAIL = os.environ.get(
    'SERVICE_ACCOUNT_EMAIL',
    f'webhook-handler@{PROJECT_ID}.iam.gserviceaccount.com'
)
```

すべてのハードコード箇所を `SERVICE_ACCOUNT_EMAIL` 変数に置換しました。

---

## Issue #20: AIの応答と外部API連携による個人情報の漏洩 (深刻度: 高)

### 発見された脆弱性

#### 個人情報の平文送信

**影響を受けるファイル:**
- `task_generator.py` (128-130行目)
- `task_personalizer.py` (48-51行目)
- `task_enhancer.py` (274行目)

**問題の詳細:**

ユーザーの個人情報（故人との関係、住所、死亡日）を平文でAI APIに送信していました：

```python
# 修正前（個人情報を平文送信）
【ユーザー情報】
- 故人との関係: 母
- お住まい: 東京都 渋谷区
- 死亡日: 2024年10月15日
```

**リスク:**
- 個人特定可能な情報の外部流出
- AIプロバイダーによるログ記録・キャッシュ
- 第三者による不正アクセス

---

### 実装した対策

#### 1. プライバシー保護ユーティリティの作成

**新規ファイル:** `privacy_utils.py`

主要機能：

```python
def anonymize_profile_for_ai(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    AIサービスに送信するプロファイルデータを匿名化

    変換例：
    - 関係性: 「母」→「親」、「祖母」→「祖父母」
    - 住所: 「東京都渋谷区」→「関東地方」
    - 死亡日: 「2024-10-15」→「1-3ヶ月」
    """
```

#### 2. タスク生成での匿名化適用

**修正内容:**

すべてのAI API呼び出し前に匿名化を実行：

```python
# task_generator.py
print("🔒 プライバシー保護: プロファイル情報を匿名化中...")
anonymized_profile = anonymize_profile_for_ai(profile)

# AI APIに送信
【ユーザー情報】（プライバシー保護のため一般化）
- 故人との関係: 親
- 地域: 関東地方
- 死亡からの経過: 1-3ヶ月
```

**修正したファイル:**
1. `task_generator.py` - 基本タスク生成
2. `task_personalizer.py` - 個別タスク生成
3. `task_enhancer.py` - Tips収集

#### 3. プライバシー保護の仕組み

| 項目 | 元のデータ | 匿名化後 |
|------|-----------|---------|
| 関係性 | 父、母、義父、義母 | 親 |
| 関係性 | 祖父、祖母 | 祖父母 |
| 関係性 | 兄、弟、姉、妹 | 兄弟姉妹 |
| 住所 | 東京都渋谷区 | 関東地方 |
| 住所 | 大阪府大阪市 | 近畿地方 |
| 死亡日 | 2024-10-15 | 1-3ヶ月 |
| 死亡日 | 2023-01-01 | 1-2年 |

---

### 修正履歴

| 日付 | 修正内容 | 担当者 |
|------|---------|--------|
| 2025-11-05 | Issue #23対応: ユーザー所有権検証の実装 | Claude Code |
| 2025-11-05 | Issue #22対応: データベース接続プール設定とリソース管理 | Claude Code |
| 2025-11-05 | Issue #21対応: Secret Managerエラーハンドリングとサービスアカウント環境変数化 | Claude Code |
| 2025-11-05 | Issue #20対応: 個人情報の匿名化実装 | Claude Code |

---

## Issue #18: セキュリティ診断 - IDOR脆弱性と機密データ保護 (深刻度: 高)

### 発見された脆弱性

#### 1. IDOR (Insecure Direct Object Reference) 脆弱性

**問題の詳細:**

タスク操作に関する複数のクエリでuser_id検証が不足しており、他のユーザーのタスクへの不正アクセスが可能でした。

**影響を受けた箇所:**

| 箇所 | 処理内容 | 脆弱なクエリ |
|------|---------|-------------|
| main.py:1036-1038 | メモ編集UPDATE | `WHERE id = :task_id` |
| main.py:1050-1052 | タスク詳細SELECT | `WHERE id = :task_id` |
| main.py:1362-1364 | タスク完了UPDATE | `WHERE id = :task_id` |
| main.py:1533-1535 | タスク詳細表示SELECT | `WHERE id = :task_id` |
| main.py:1629-1631 | ポストバック完了UPDATE | `WHERE id = :task_id` |
| main.py:1717-1719 | ポストバック未完了UPDATE | `WHERE id = :task_id` |

**攻撃シナリオ:**

攻撃者が他のユーザーのtask_idを推測または取得し、以下の操作が可能でした：
- 他人のタスクの閲覧
- 他人のタスクの編集・削除
- 他人のタスクステータスの変更

---

### 実装した対策

#### 1. 全タスク操作へのuser_id検証追加

**修正内容:**

すべてのタスク関連クエリのWHERE句に`AND user_id = :user_id`を追加：

```python
# 修正前（脆弱）
UPDATE tasks
SET metadata = CAST(:metadata AS jsonb)
WHERE id = :task_id

# 修正後（セキュア）
UPDATE tasks
SET metadata = CAST(:metadata AS jsonb)
WHERE id = :task_id AND user_id = :user_id
```

**修正した箇所:**
1. メモ編集UPDATE (main.py:1036-1038)
2. タスク詳細SELECT (main.py:1050-1052)
3. タスク完了UPDATE (main.py:1362-1364)
4. タスク詳細表示SELECT (main.py:1533-1535)
5. ポストバック完了UPDATE (main.py:1629-1631)
6. ポストバック未完了UPDATE (main.py:1717-1719)

#### 2. ポストバックイベントでの認証強化

**修正内容 (main.py:1520-1539):**

`handle_postback`関数の先頭で、line_user_idからuser_idを取得し、認証を実施：

```python
def handle_postback(event: PostbackEvent):
    """ポストバックイベント処理"""
    line_user_id = event.source.user_id

    # line_user_idからuser_idを取得（認証）
    with engine.connect() as conn:
        user_result = conn.execute(
            sqlalchemy.text("SELECT id FROM users WHERE line_user_id = :line_user_id"),
            {"line_user_id": line_user_id}
        ).fetchone()

        if not user_result:
            # ユーザーが見つからない場合はエラー
            return

        user_id = user_result[0]

    # 以降、すべてのクエリでuser_idを使用
```

---

#### 2. 機密データの暗号化

**問題の詳細:**

`user_profiles`, `follow_up_questions`, `conversation_history`テーブルの機密データ（死亡日、財務情報、家族関係など）が平文で保存されています。

**実装済みの対策:**

Issue #20で既に実装：
- 外部AI APIへの送信前に個人情報を匿名化
- プライバシー保護ユーティリティ（privacy_utils.py）を導入

**追加の推奨事項:**

##### データベースレベルの暗号化（Infrastructure）

Cloud SQLでの保存時暗号化（Encryption at Rest）を有効化：

```bash
# Cloud SQL インスタンス作成時
gcloud sql instances create INSTANCE_NAME \
  --database-version=POSTGRES_14 \
  --tier=db-f1-micro \
  --region=asia-northeast1 \
  --encryption-key=projects/PROJECT_ID/locations/LOCATION/keyRings/KEY_RING/cryptoKeys/KEY_NAME
```

##### アプリケーションレベルの暗号化（将来の実装）

特に機密性の高いフィールドに対するフィールドレベル暗号化：

```python
# 将来の実装例
from cryptography.fernet import Fernet

class EncryptedField:
    def __init__(self, key):
        self.cipher = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self.cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self.cipher.decrypt(ciphertext.encode()).decode()

# 使用例
encrypted_death_date = cipher.encrypt(death_date)
# データベースに保存
```

##### アクセス制御の強化

最小権限の原則：
- アプリケーション用データベースユーザーの権限を最小限に制限
- 読み取り専用と読み書き可能なユーザーを分離
- 定期的な権限監査

---

### セキュリティ強化の効果

| 対策 | 効果 |
|------|------|
| IDOR脆弱性の修正 | 他ユーザーのタスクへの不正アクセスを完全に防止 |
| ポストバック認証強化 | イベント処理の最初に認証を実施 |
| 個人情報匿名化（Issue #20） | 外部APIへのデータ流出リスクを最小化 |

---

### 修正履歴

| 日付 | 修正内容 | 担当者 |
|------|---------|--------|
| 2025-11-05 | Issue #23対応: ユーザー所有権検証の実装 | Claude Code |
| 2025-11-05 | Issue #22対応: データベース接続プール設定とリソース管理 | Claude Code |
| 2025-11-05 | Issue #21対応: Secret Managerエラーハンドリングとサービスアカウント環境変数化 | Claude Code |
| 2025-11-05 | Issue #20対応: 個人情報の匿名化実装 | Claude Code |
| 2025-11-05 | Issue #18対応: IDOR脆弱性の修正と機密データ保護の推奨事項 | Claude Code |

---

### 参考資料

- GitHub Issue: #18, #20, #21, #22, #23
- OWASP Top 10 - Broken Access Control
- OWASP Top 10 - Insecure Direct Object References (IDOR)
- CWE-639: Authorization Bypass Through User-Controlled Key
- CWE-922: Insecure Storage of Sensitive Information
