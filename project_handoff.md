# メール抽出AI営業アシスタント開発プロジェクト 引き継ぎ資料

## 1. プロジェクト概要
日本国内の中小企業・個人事業主のメールボックス（Mbox形式、約52GB）から「人脈資産」を抽出し、営業優先順位をスコアリングするAIアシスタントの開発。

## 2. 現在のステータス
- **Phase 1 (データ基盤構築)** の途中。
- `knowhow` プロジェクトで誤って作業していたため、`pastlead` プロジェクトへの完全移行が必要。
- DB技術選定、スキーマ設計、インポートスクリプトのプロトタイプ作成まで完了。
- **直近の課題:** MboxインポートスクリプトでSQLiteへの誤接続エラーが発生していた（修正版コードはこのドキュメントに同梱）。

## 3. 技術スタック
- **Frontend**: Next.js (TypeScript) + Vanilla CSS/Modules
- **Backend**: FastAPI (Python)
- **Database**: PostgreSQL + pgvector (Dockerで運用)
- **Environment**: Local Mac
- **LLM**: Local LLM (Ollama via API) for filtering, Gemini/OpenAI for final output.

## 4. データベース設計 (PostgreSQL)
- `contacts`: 連絡先情報（名前、メール、親密度スコア）
- `threads`: スレッド情報（Subject、親子関係）
- `messages`: メッセージ本体 + ベクトル埋め込み (content_vector)

## 5. 次のアクション（移行後の手順）
1. `pastlead` ディレクトリで `initial_setup_script.sh` を実行する。
   - これにより、`backend/`, `frontend/`, `docker-compose.yml` 等が自動生成されます。
2. Dockerを起動する (`docker-compose up -d`)。
3. Python仮想環境を作成し、依存ライブラリをインストールする。
4. 以下のコマンドでテストインポートを実行する。
   ```bash
   # Mboxの先頭100MBを切り出し
   dd if="/Users/egawahideaki/claude-code-project/pastlead/すべてのメール（迷惑メール、ゴミ箱のメールを含む）-002.mbox" of="test_head.mbox" bs=1m count=100
   
   # インポート実行
   source venv/bin/activate
   export PYTHONPATH=$PYTHONPATH:$(pwd)/backend
   python backend/scripts/import_mbox.py test_head.mbox
   ```

## 6. 実装コード（自動生成スクリプトに含まれますが、念のため記載）

### Database Schema (backend/app/models.py)
- PostgreSQL専用ドライバ (`postgresql+psycopg2`) を明示的に指定。
- `BigInteger` を主キーに使用し、`autoincrement=True` を設定。
- スキーマ定義：Contacts, Threads, Messages (with pgvector).

### Import Script (backend/scripts/import_mbox.py)
- Mbox形式（Google Takeout等）をストリーミング読み込み。
- 自動送信メール、メルマガの除外フィルタ実装済み。
- PostgreSQLへのUPSERT処理（`ON CONFLICT`）を実装済み。
