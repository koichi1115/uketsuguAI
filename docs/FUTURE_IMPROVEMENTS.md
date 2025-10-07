# 将来の改善計画

## 1. Google Search GroundingによるリアルタイムWeb検索【✅ 実装済み】

### 実装状況
- **実装済み（2025年10月7日）**: Gemini 2.5 Pro + Google Search Groundingを使用
- e-gov、自治体サイト、法務省・厚労省・国税庁の公式情報をリアルタイム検索
- X（Twitter）、ブログからSNS・口コミの実用的なTipsを収集
- 動的に最新情報を取得してタスク生成

### 追加実装予定
**第1段階: Tavily Search APIの追加統合（より深い口コミ収集）**
- Google Search Groundingに加えて、Tavily Search APIも並行使用
- より多様な情報源から体験談を収集
- 実装予定時期: 2025年Q3-Q4
- 推定コスト: 月$20-30

**第2段階: キャッシング・インデキシング**
- よく検索される情報（基本的な手続き）をキャッシュして高速化
- 自治体ごとの窓口情報をインデキシング
- 実装予定時期: 2025年Q4

### 現在の実装（Gemini 2.5 Pro + Google Gen AI SDK）
**重要**: Google Search GroundingとJSON Schemaは同時使用不可のため、2段階アプローチを採用
**SDK**: 新しい`google-genai`パッケージに移行済み（2025年10月7日）

```python
# task_generator.py の実装（2段階アプローチ）
from google import genai
from google.genai import types

client = genai.Client(api_key=gemini_api_key)

# 第1段階: Gemini 2.5 ProでGoogle Search Groundingによる情報収集
grounding_response = client.models.generate_content(
    model='gemini-2.5-pro',
    contents=prompt,
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())]
    )
)
collected_info = grounding_response.text

# 第2段階: Gemini 2.5 ProでJSON Schema構造化
structuring_response = client.models.generate_content(
    model='gemini-2.5-pro',
    contents=structuring_prompt,
    config=types.GenerateContentConfig(
        response_mime_type='application/json',
        response_schema=task_schema
    )
)
```

### ユーザーへの情報時点明示
- **現在**: 「2025年10月7日時点の最新情報」と動的に表示 ✅ 実装済み
- **将来**: タスク詳細に「最終更新日」フィールドを追加

---

## 2. タスク管理機能の強化

### 追加予定機能
- タスク追加（ユーザーが手動でタスクを追加）
- タスク編集（期限変更、優先度変更、メモ追加）
- タスク削除（不要なタスクを削除）
- タスクの並び替え（ドラッグ&ドロップ）

実装予定時期: 2025年Q3

---

## 3. プロフィール編集機能

### 追加予定機能
- 死亡日の修正
- 故人との関係の変更
- 住所の更新
- プロフィールリセット

実装予定時期: 2025年Q3

---

## 4. 通知機能

### 追加予定機能
- タスク期限リマインダー（3日前、1日前、当日）
- LINEプッシュ通知
- 期限超過アラート

実装予定時期: 2025年Q4

---

## 5. 他の機能拡張

### 検討中
- 遺品整理・生前整理のアドバイス
- 相続人間のタスク共有機能
- 手続き完了証明書のアップロード・保管
- チャットボットでの手続き相談

---

**最終更新日**: 2025年10月7日
**作成者**: Claude Code + Koichi Shimada
