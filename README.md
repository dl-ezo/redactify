# Redactify

PDFから個人情報を自動検出して黒塗りするツール

## 特徴

- **AI搭載ファジーマッチング**: 表記揺れや類似表現を自動検出
- **完全な黒塗り**: PyMuPDFによる真のテキスト削除（コピー&ペーストでも復元不可）
- **一括処理**: フォルダ内のすべてのPDFを自動処理
- **プレビューモード**: 検出結果を事前確認
- **柔軟な出力**: PDF形式または画像形式で出力
- **CLI + Web両対応**: コマンドライン・Webブラウザ両方で利用可能
- **メモリベース処理**: ファイルがサーバーに残らない安全設計
- **自動バージョン管理**: Gitタグベースの動的バージョン表示

## インストール

```bash
git clone https://github.com/your-username/redactify.git
cd redactify
pip install -r requirements.txt
```

## 設定

### 1. 設定ファイルの作成

```bash
cp config.json.sample config.json
```

### 2. AI設定（環境変数優先）

.envファイルを作成（推奨）：

```bash
cp .env.sample .env
```

.envファイルを編集：

```bash
# AI機能の有効/無効
AI_ENABLED=true

# AIプロバイダー（anthropic または openai）
AI_PROVIDER=anthropic

# AIモデル
AI_MODEL=claude-3-haiku-20240307

# APIキー
ANTHROPIC_API_KEY=sk-ant-api03-...
```

または直接環境変数で設定：

```bash
export AI_ENABLED=true
export AI_PROVIDER=anthropic
export AI_MODEL=claude-3-haiku-20240307
export ANTHROPIC_API_KEY="sk-ant-api03-..."
export OPENAI_API_KEY="sk-..."
```

**設定の優先度**: 環境変数/.env > config.json > デフォルト値

これにより、本番環境では環境変数で設定を上書きしつつ、開発環境ではconfig.jsonを使用できます。

### 3. OpenAI を使用する場合

```bash
# .envファイルまたは環境変数で設定
AI_PROVIDER=openai
AI_MODEL=gpt-3.5-turbo
OPENAI_API_KEY=sk-...
```

## 使用方法

### Webアプリケーション（推奨）

```bash
# Webサーバーを起動
python app.py
```

ブラウザで `http://localhost:5000` にアクセスして利用：

1. 「消したい情報」欄に黒塗りしたい情報を入力
2. PDFファイルを選択（複数可）
3. 「黒塗り処理を開始」ボタンをクリック
4. 処理完了後、ZIPファイルをダウンロード

**セキュリティ**: アップロードファイルはメモリ内で処理され、サーバーに保存されません。

### コマンドライン（CLI）

```bash
# プレビューモード（検出確認）
python redactify.py --preview

# 実際に黒塗り実行
python redactify.py

# 特定のファイルのみ処理
python redactify.py input.pdf

# 画像として出力
python redactify.py --image
```

### 詳細オプション

```bash
# ヘルプ表示
python redactify.py --help

# 設定ファイル指定
python redactify.py --config my-config.json

# 出力ファイル名指定
python redactify.py input.pdf --output output.pdf

# すべてのPDFを処理
python redactify.py --all
```

## 設定ファイル

### 基本設定

```json
{
  "folders": {
    "input_dir": "./input",
    "output_dir": "./output"
  },
  "ai_api": {
    "provider": "anthropic",
    "api_key": "your-api-key",
    "model": "claude-3-haiku-20240307",
    "enabled": true
  },
  "target_patterns": [
    "検出したい住所や個人情報のサンプル"
  ]
}
```

### AI検出パターン

`target_patterns`には検出したい個人情報の完全な例を記載：

```json
{
  "target_patterns": [
    "100-0001 東京都千代田区千代田１－１－１",
    "090-1234-5678",
    "example@email.com",
    "田中太郎"
  ]
}
```

### 正規表現パターン（オプション）

確実に検出したい定型パターンがある場合：

```json
{
  "legacy_patterns": {
    "custom_patterns": [
      "〒\\d{3}-\\d{4}",
      "\\d{2,4}-\\d{2,4}-\\d{4}",
      "[\\w\\.-]+@[\\w\\.-]+\\.[a-zA-Z]{2,}"
    ]
  }
}
```

## 検出方式

### AI検出（推奨）
- **柔軟性**: 表記揺れ、改行、スペースの違いを自動検出
- **学習能力**: 類似パターンを推論
- **例**: "神奈川県横浜市" → "ｶﾅｶﾞﾜｹﾝﾖｺﾊﾏｼ"も検出

### 正規表現検出
- **確実性**: 完全一致による確実な検出
- **高速**: 大量処理に適している
- **例**: `〒\d{3}-\d{4}` で郵便番号形式を確実に検出

## セキュリティ

### プライバシー保護
- **メモリベース処理**: アップロードファイルがサーバーに保存されない
- **一時ファイル不使用**: ディスクI/Oを使わないメモリ内処理
- **自動クリーンアップ**: 処理完了後にメモリから自動削除
- **セッション管理**: ユーザーごとに独立したメモリ領域

### 真の黒塗り
- **PyMuPDF**: `apply_redactions()`による物理的なテキスト削除
- **復元不可**: コピー&ペースト、テキスト選択で復元不可能
- **完全削除**: 元のテキストデータが存在しなくなる

### 検出漏れ対策
1. **プレビューモード**: 事前に検出結果を確認
2. **複数パターン**: 様々な表記パターンを設定
3. **AI + 正規表現**: 両方式の併用で検出精度向上

## 対応形式

### 入力
- PDF形式のみ

### 出力
- **PDF形式**: 元のレイアウトを保持（デフォルト）
- **PNG形式**: 画像として出力（`--image`オプション）

## トラブルシューティング

### よくある問題

**1. APIキーエラー**
```
AI機能が有効ですがAPIキーが設定されていません
```
→ config.jsonまたは環境変数でAPIキーを設定

**2. 設定ファイルエラー**
```
エラー: target_patternsまたはlegacy_patternsを設定してください
```
→ config.jsonに検出パターンを設定

**3. ファイルが見つからない**
```
エラー: ./input にPDFファイルが見つかりません
```
→ 入力フォルダにPDFファイルを配置、またはファイルパスを直接指定

### デバッグ方法

```bash
# 検出内容を確認
python redactify.py --preview

# 単一ファイルで動作確認
python redactify.py test.pdf --preview

# 設定ファイルを明示指定
python redactify.py --config config.json --preview
```

## ライセンス

MIT License

## 開発

### リリース管理

バージョンはGitタグで管理され、Webアプリケーションに自動反映されます：

```bash
# 新バージョンをリリース
git tag -a v0.2.0 -m "新機能の追加"
git push origin --tags

# アプリを再起動すると自動的にバージョン表示が更新される
```

### 自動デプロイ

GitHub Actionsにより、mainブランチへのpushで自動デプロイされます：

1. GitHub Secretsの設定が必要：
   - `HEROKU_API_KEY`: HerokuのAPIキー
   - `HEROKU_APP_NAME`: Herokuアプリ名
   - `HEROKU_EMAIL`: Herokuアカウントのメール

2. 環境変数の設定：
   ```bash
   # Herokuアプリに環境変数を設定
   heroku config:set AI_ENABLED=true --app your-app-name
   heroku config:set AI_PROVIDER=anthropic --app your-app-name
   heroku config:set ANTHROPIC_API_KEY=your-key --app your-app-name
   ```

### 貢献

プルリクエストやイシューを歓迎します。

## 免責事項

- このツールは個人情報の検出・削除を支援しますが、100%の検出を保証するものではありません
- 重要な文書については、必ずプレビューモードで検出結果を確認してください
- 法的な責任は使用者が負うものとします