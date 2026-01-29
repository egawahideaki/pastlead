# PastLead プロジェクト開発・環境構築マニュアル

このドキュメントは、52GB規模の巨大MboxデータをPostgreSQL + pgvectorデータベースへインポートし、AI営業アシスタントの基盤を構築するための手順書です。

## 1. 前提条件

- **OS**: macOS (推奨), Linux
- **必須ツール**:
  - Docker Desktop (または Docker Engine + Compose)
  - Python 3.10以上
  - Git
- **データ**:
  - Google Takeout等からエクスポートした `.mbox` ファイル（例: `すべてのメール（迷惑メール、ゴミ箱のメールを含む）-002.mbox`）

## 2. プロジェクトの初期セットアップ

プロジェクトディレクトリを作成し、初期構築スクリプトを実行します。これにより、必要なディレクトリ構成、Docker設定、Pythonスクリプトが自動生成されます。

### 2.1 スクリプト実行による自動構築

プロジェクトルート（例: `pastlead/`）にて以下のコマンドを実行してください。

```bash
chmod +x initial_setup_script.sh
./initial_setup_script.sh
```

実行後、以下のディレクトリ・ファイルが生成されていることを確認してください。
- `backend/` (アプリケーションコード, スクリプト)
- `frontend/` (空ディレクトリ)
- `docker-compose.yml` (DB設定)
- `resume_import.sh` (再開用スクリプト)

### 2.2 データベースの起動

Dockerを使用してPostgreSQLを起動します。

```bash
docker-compose up -d
```

起動後、`pgvector` 拡張機能を手動で有効化します（初回のみ）。

```bash
docker exec -i knowhow_db psql -U user -d knowhow_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 2.3 Python環境の準備

仮想環境を作成し、依存ライブラリをインストールします。

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

---

## 3. データインポート（Mbox → PostgreSQL）

巨大なMboxファイルのインポートは長時間かかるため、標準ライブラリではなく**高速版スクリプト**を使用し、さらに中断しても再開可能な仕組みを利用します。

### 3.1 ファイルの配置

インポートしたい `.mbox` ファイルをプロジェクトルートに配置してください。
（必要に応じて `backend/scripts/import_mbox_fast.py` 内のファイルパスや `resume_import.sh` を修正してください）

### 3.2 インポートの実行

以下のシェルスクリプトを実行してインポートを開始します。このスクリプトは以下の機能を持っています：
- バックグラウンド実行 (`nohup`)
- リアルタイムログ出力 (`-u` オプション)
- **レジューム機能**（中断しても、次回実行時に続きから再開）

```bash
./resume_import.sh
```

### 3.3 進捗の確認

インポート処理はバックグラウンドで動作します。以下のコマンドでログをリアルタイム監視できます。

```bash
tail -f import.log
```

- **処理速度目安**: 約 300〜400件/秒
- **所要時間**: 50GB（約52万件）で約30〜40分

### 3.4 処理の中断と再開

PCのスリープや予期せぬシャットダウンで処理が止まった場合でも、データベースには「最後に成功したバッチ（1000件単位）」までの進捗が `import_progress.json` に保存されています。

**再開手順**:
再び `./resume_import.sh` を実行するだけです。自動的に未処理の部分からスタートします。

---

## 4. データベース構成

インポートされるデータは以下のテーブルに格納されます。

- **contacts**: 連絡先（メールアドレス、名前）
- **threads**: スレッド情報（件名、タイムスタンプ）
- **messages**: メッセージ本体
  - `message_id`: メール固有ID
  - `content_body`: 本文（初期は "Pending extraction"）
  - `metadata_`: To, Cc, References等のヘッダ情報 (JSONB)
  - `content_vector`: ベクトル埋め込み用カラム (768次元, HNSWインデックス対応)

### 確認コマンド例

```bash
# 登録件数の確認
docker exec -i knowhow_db psql -U user -d knowhow_db -c "select count(*) from messages;"
```

## 5. トラブルシューティング

**Q. ログが出ない / 止まっているように見える**
- `tail -f import.log` で確認してください。Pythonのバッファリングにより遅延することがありますが、`resume_import.sh` は `-u` オプションを使用しているため基本的にリアルタイムです。

**Q. "UniqueViolation" エラーが出る**
- Mbox内に重複メールが含まれる場合に発生しますが、スクリプトは `ON CONFLICT DO NOTHING` (無視) でスキップするように対策済みです。

**Q. 非常に遅い**
- `import_mbox.py` (標準版) ではなく `import_mbox_fast.py` (高速版) が使用されているか確認してください。高速版はファイルをバイナリモードで直接読み込みます。
