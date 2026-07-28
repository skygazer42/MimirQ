<div align="center">

<img src="./images/logo.png" alt="MimirQ: 検査・回帰・ガバナンス可能なオープンソース RAG ナレッジベース" width="100%"/>

<p><b>フルスタックでオープンソース、中国語ファーストのエンタープライズ RAG ナレッジベース</b><br/>ドキュメントがどうチャンク分割されるか、検索が実際に何にヒットするか、なぜその回答が生成されるのか——チェーン全体を検査・デバッグ・回帰テストできます。</p>

<p>
  <a href="#-クイックスタート"><b>クイックスタート</b></a> ·
  <a href="#-プロダクト画面"><b>プロダクト画面</b></a> ·
  <a href="#-dify-連携"><b>Dify 連携</b></a> ·
  <a href="#-実運用で検証済み"><b>800問ベンチマーク</b></a> ·
  <a href="https://skygazer42.github.io/MimirQ/"><b>API ドキュメント</b></a>
</p>

<p>
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License: Apache 2.0"/></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"/></a>
  <img src="https://img.shields.io/badge/Dify-External_Knowledge_%2B_HTTP-1C64F2" alt="Dify External Knowledge and HTTP integration"/>
  <img src="https://img.shields.io/badge/Benchmark-800_questions-0F766E" alt="800-question benchmark"/>
</p>

<p>
  <a href="./README.md"><img src="https://img.shields.io/badge/简体中文-d9d9d9" alt="简体中文"/></a>
  <a href="./README_EN.md"><img src="https://img.shields.io/badge/English-d9d9d9" alt="English"/></a>
  <a href="./README_JA.md"><img src="https://img.shields.io/badge/日本語-d9d9d9" alt="日本語"/></a>
  <a href="./README_KO.md"><img src="https://img.shields.io/badge/한국어-d9d9d9" alt="한국어"/></a>
</p>

</div>

---

## 💡 MimirQ とは

**MimirQ**（知恵の泉を守る北欧神話の番人 **Mímir** に由来）は、**フルチェーンの可観測性**に注力した RAG ナレッジベース Q&A プラットフォームです。フロントエンドとバックエンドの両方がオープンソースで、Docker Compose または Helm でデプロイできます。

<table>
  <tr>
    <td align="center" width="25%"><strong>30</strong><br/><sub>パース基盤</sub></td>
    <td align="center" width="25%"><strong>86</strong><br/><sub>チャンク分割戦略</sub></td>
    <td align="center" width="25%"><strong>13</strong><br/><sub>リランカー</sub></td>
    <td align="center" width="25%"><strong>800</strong><br/><sub>固定問題セット評価</sub></td>
  </tr>
</table>

<table>
  <tr>
    <td width="50%"><strong>見える</strong><br/><sub>パース結果、チャンク境界、検索とリランクの過程</sub></td>
    <td width="50%"><strong>追跡できる</strong><br/><sub>文単位の引用、バージョン、エビデンス、完全なトレース</sub></td>
  </tr>
  <tr>
    <td><strong>守れる</strong><br/><sub>ドキュメント ACL、RBAC、マスキング、監査、セーフティレール</sub></td>
    <td><strong>回帰できる</strong><br/><sub>ゴールデンセット、評価ダッシュボード、リリースゲート</sub></td>
  </tr>
</table>

<details>
<summary><b>なぜ MimirQ を作ったのか？</b></summary>

MimirQ は、ある行政サービスの Q&A プロジェクトから生まれました。システムは質問に答えられていたものの、回答が誤ったときに、その原因がパース・チャンク分割・検索・リランク・生成のどこにあるのかを明確に切り分けられませんでした。行政ナレッジには地域ごとの版、政策の更新、スキャン文書や表があり、流暢だが古い政策を引用した回答は、「わかりません」と明言するよりも危険です。

既存プラットフォームはワークフローやエージェントには強い一方で、RAG のトラブルシューティングに必要なパース・インデックス・検索・引用・評価は、別々のコンポーネントに散在しがちです。MimirQ は汎用のノードキャンバスをもう一つ作るのではなく、検査可能な RAG チェーンに注力します。

> **MimirQ が解こうとしているのは「RAG が動くかどうか」ではなく、「なぜその RAG が信頼に値するのか」です。**

</details>

---

## 🚀 クイックスタート

### 前提条件

- [Docker](https://docs.docker.com/get-docker/) 20.10+ & [Docker Compose](https://docs.docker.com/compose/install/) 2.0+
- GNU Make。Docker 起動ではローカル設定の生成に Python 3.9+ も必要
- ホストでのソース起動では Python 3.11+、Node.js 20+、pnpm 10.26 も必要
- 最低 4 CPU コア / 16 GB RAM / 50 GB ディスク

### 共通準備

```bash
git clone --depth 1 --single-branch https://github.com/skygazer42/MimirQ.git
cd MimirQ
make init
```

`make init` は完全な `.env` とランダムな JWT `SECRET_KEY` を生成します。`.env` は高度な設定リファレンスであり、一行ずつ埋めるフォームではありません。デフォルトの SiliconFlow 構成では、必須項目は次の一つだけです。

```dotenv
# 唯一の必須項目
LLM_API_KEY=<your-siliconflow-api-key>
```

| 起動方法 | 用途 | アプリの実行場所 |
|:---|:---|:---|
| **Docker 一括起動（推奨）** | 初回利用、サーバーデプロイ | Web、API、Worker、依存サービスをコンテナで実行 |
| **ホストでソース起動** | フロントエンド・バックエンド開発、ホットリロード | Web、API、Worker はホスト、依存サービスは Docker で実行 |

### 方法 1：Docker で一括起動

```bash
make up-web
make ps
curl --noproxy '*' -f http://localhost:8000/api/v1/health/ready
```

`make up-web` は Web アプリ、API、Worker、Postgres、Milvus、Etcd、MinIO、Redis を起動します。既存の設定は上書きされません。[http://localhost:3000](http://localhost:3000) を開いてローカルアカウントを作成すればシステムに入れます。

初回の Docker ビルドでは、固定バージョンの DeepDoc モデルバンドルをダウンロードして検証します。プロキシが Linux ホストのループバックでのみ待ち受けている場合は、Docker 側でローカルに設定するか、`DOCKER_BUILD_NETWORK=host make up-web` を実行します。プロキシアドレスはコミットしないでください。Docker Hub に接続できない場合は、`.env` の `MILVUS_IMAGE` を信頼できるレジストリ上の同一バージョンのイメージに変更できます。

Web スタック全体を停止します。

```bash
docker compose --env-file .env \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.web.yml down
```

### 方法 2：フロントエンドとバックエンドをホストで起動

ホスト側の依存関係をインストールし、基盤サービスを起動します。

```bash
make setup-host
```

`make setup-host` は `.venv` を作成し、CPU 版バックエンド依存関係と Web 依存関係をインストール・検証し、固定パーサーモデルを取得して Postgres、Milvus、Etcd、MinIO、Redis を起動します。既存の `.env` は上書きしません。

3 つのターミナルを開きます。

```bash
# ターミナル 1：FastAPI（ホットリロード）
make backend

# ターミナル 2：文書パース・インデックス Worker
make worker

# ターミナル 3：Next.js（ホットリロード）
make web
```

ホスト側のサービスを確認します。

```bash
make infra-ps
curl --noproxy '*' -f http://localhost:8000/api/v1/health/ready
```

3 つのホストプロセスを終了した後、`make infra-down` で依存サービスを停止します。

### サービス URL

| サービス | URL |
|:---:|:---|
| **フロントエンド UI** | [http://localhost:3000](http://localhost:3000) |
| **API ドキュメント** | [http://localhost:8000/docs](http://localhost:8000/docs) |

> 軽量構成には `make up-lite` を使用できます。Milvus を Chroma/FAISS に置き換えて MinIO を省きますが、デフォルトではフロントエンドを起動しません。UI が必要な場合は別途 `make web` を実行してください。外部 LLM / Embedding の呼び出しには、自分のモデルプロバイダーの認証情報が必要です。

| シナリオ | 変更 | 必須？ |
|:---|:---|:---:|
| デフォルトの SiliconFlow LLM + Embedding | `LLM_API_KEY` | **はい** |
| 別のチャットプロバイダーやモデル | `LLM_API_BASE`, `LLM_MODEL` | いいえ |
| Embedding を別プロバイダーに | `EMBEDDING_API_KEY`, `EMBEDDING_API_BASE`, `EMBEDDING_MODEL` | いいえ。キーと URL を空にすると LLM 設定を再利用 |
| SiliconFlow リランカー | `ENABLE_RERANKER=true` | いいえ。検索レイテンシを避けるためデフォルト無効、LLM キーを再利用 |
| MinerU のオンライン PDF パース | `MINERU_ENABLED=true`, `MINERU_API_TOKEN` | いいえ。アップロード時に `mineru` を選択 |
| その他すべての `.env` 設定 | 変更なし | いいえ。デフォルトのまま |

モデル ID は SiliconFlow の `/v1/models` レスポンスに存在する必要があります。検証済みのチャットモデルには `Qwen/Qwen3-32B` と `Qwen/Qwen3-8B`、検証済みの Embedding モデルには `BAAI/bge-m3` と `Qwen/Qwen3-Embedding-0.6B`、検証済みのリランカーには `BAAI/bge-reranker-v2-m3` があります。Embedding モデルを変更した後は、既存のナレッジベースのインデックスを再構築してください。新旧のベクトルを混在させてはいけません。認証情報は [SiliconFlow コンソール](https://cloud.siliconflow.cn/account/ak) と [MinerU](https://mineru.net/) で作成し、実際のキーはローカルの `.env` のみに保管してください。

### 行政サービスプラグインのサンプルを実行する

リポジトリには、6 つのソース系統（サービス項目、ワンストップサービス、よくある質問、テーマ別 FAQ、部門 FAQ、地区 FAQ）向けの小さな公開サンプルを含む常州行政サービスナレッジプラグインが含まれています。データベースを起動せずに、ガバナンス・チャンク分割・KG 出力・ゴールデン草案を検証できます。

```bash
make changzhou-gov-plugin-test-report
make changzhou-gov-plugin-chunk-report
```

レポートは `/tmp/changzhou_gov_plugin_*` に出力されます。これらのコマンドはデータベース・ベクトルストア・KG に書き込みません。サンプルパス、プラグイン参照、実コーパスのクローズドループコマンドについては[プラグインガイド](./plugins/pipelines/changzhou-gov-service-knowledge/README.md)を参照してください。

高度なモデル、パーサー、プロキシ設定は [`.env.example`](./.env.example) を参照してください。Embedding モデルを変更した後は、既存のナレッジベースのインデックスを再構築する必要があります。その他のプラットフォームや Windows の手順は[開発ガイド](./docs/quickstart.md)を参照してください。

---

## 🖼️ プロダクト画面

以下の画面は、リポジトリに含まれる公開の行政サービスプラグインサンプルで生成しています。本番のナレッジベースデータは含まれていません。

<table>
  <tr>
    <td colspan="2" align="center">
      <img src="./docs/images/screenshots/knowledge-graph.png" alt="MimirQ ナレッジグラフ画面" width="100%"/>
      <br/><strong>ナレッジグラフ</strong>
      <br/><sub>エンティティ・イベント・関係を一つのキャンバスで検索・分析。</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/dataset-management.png" alt="MimirQ ナレッジベース管理画面" width="100%"/>
      <br/><strong>ナレッジベース管理</strong>
      <br/><sub>データセット・ドキュメント・チャンク・取り込み状況を一元的に把握。</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/rag-evaluation.png" alt="MimirQ ゴールデン回帰評価画面" width="100%"/>
      <br/><strong>ゴールデン回帰評価</strong>
      <br/><sub>標準 Q&A、実行履歴、Recall / MRR などの指標を同一画面で確認。</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/settings.png" alt="MimirQ システム設定画面" width="100%"/>
      <br/><strong>システム設定</strong>
      <br/><sub>依存関係の状態、パース能力、モデルサービス連携を一元的に確認。</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/chat-history.png" alt="MimirQ 会話履歴とエビデンス確認画面" width="100%"/>
      <br/><strong>会話履歴とエビデンス確認</strong>
      <br/><sub>過去のセッションを検索し、完全な回答・出典・フィードバック導線を振り返り。</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/ingestion-monitor.png" alt="MimirQ 取り込み実行モニター" width="100%"/>
      <br/><strong>取り込み実行モニター</strong>
      <br/><sub>データセットごとにパース・チャンク分割・ガバナンス・エクスポート・再試行の状態を監視。</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/data-governance.png" alt="MimirQ データガバナンスワークベンチ" width="100%"/>
      <br/><strong>データガバナンス</strong>
      <br/><sub>ドキュメントのプレビュー・品質チェック・クレンジング・アノテーションを一つのワークベンチで。</sub>
    </td>
  </tr>
</table>

---

## 🔌 Dify 連携

MimirQ は、ワークフローキャンバスを再実装することなく、ガバナンス可能な RAG レイヤーとして既存の Dify アプリに組み込めます。現在、2 つの方式をサポートしています。

- **External Knowledge API**：Dify がオーケストレーションと生成を担い、MimirQ がドキュメントガバナンス・検索・リランク・権限フィルタリング・エビデンス返却を担います。
- **Workflow HTTP ノード**：Dify がカスタムルーティングとパラメータを担い、MimirQ が指定されたナレッジ範囲に対してエビデンスとトレースを返します。

### Workflow HTTP ノード

<p align="center">
  <a href="./docs/images/screenshots/dify-mimirq-http-workflow.png">
    <img src="./docs/images/screenshots/dify-mimirq-http-workflow.png" alt="Dify HTTP ノードが MimirQ の検索 API を呼び出しエビデンスをマージ" width="1100" style="max-width: 100%; height: auto;"/>
  </a>
  <br/>
  <sub>実際の Dify HTTP サブチェーン（マスキング済み）：JSON リクエストを安全に構築 → HTTP ノードが MimirQ の retrieval エンドポイントを呼び出し → 結果を変換 → ナレッジエビデンスをマージ。</sub>
</p>

### External Knowledge API

<p align="center">
  <a href="./docs/images/screenshots/dify-mimirq-workflow.png">
    <img src="./docs/images/screenshots/dify-mimirq-workflow.png" alt="Dify ワークフローが地域ルーティングで 8 つの MimirQ 行政ナレッジベースに接続" width="560" style="max-width: 100%; height: auto;"/>
  </a>
  <br/>
  <sub>実際の Dify Chatflow（マスキング済み）：緑色のナレッジ検索ノードが External Knowledge API 経由で MimirQ を呼び出し、エビデンスを統一的にマージ。クリックで原寸表示。</sub>
</p>

> 図中の地域ルーティングはオプションのサンプルプラグインによるものです。MimirQ コアは地域・事項・業種ルールを内蔵しません。

Dify 標準の外部ナレッジベースエンドポイントは `POST /api/v1/integrations/dify/retrieval` です。オプションで `POST /api/v1/integrations/dify/conversation-turns` を使って、回答・引用・会話識別子を返送できます。設定は [`.env.example`](./.env.example)、デプロイ前の検証は [readiness gate](./scripts/README.md)、実測結果は[実運用で検証済み](#-実運用で検証済み)を参照してください。

---

## 🧭 主要機能の比較

<details>
<summary><b>Dify、RAGFlow、FastGPT、AnythingLLM、LangChain との機能比較を開く</b></summary>


| 機能領域 | **MimirQ** | [Dify](https://github.com/langgenius/dify) | [RAGFlow](https://github.com/infiniflow/ragflow) | [FastGPT](https://github.com/labring/FastGPT) | [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | [LangChain](https://github.com/langchain-ai/langchain) |
|:---|:---|:---|:---|:---|:---|:---|
| **ドキュメントパース** | **30 のパース基盤**：PDF、OCR、レイアウト、表、数式、VLM | Knowledge Pipeline；PDF、PPT など一般的な形式 | **DeepDoc**；複雑なレイアウトとスキャン；MinerU / Docling | PDF・スキャン・表・数式を Markdown 化 | PDF、TXT、DOCX などのドキュメントパイプライン | Document Loaders とサードパーティパーサー連携 |
| **チャンク分割** | **86 種の戦略**：再帰、セマンティック、親子、RAPTOR、Late Chunking；可視化プレビュー | 汎用、親子、Q&A、パイプライン定義の処理 | テンプレートベースのチャンク分割；可視化した人手介入 | 自動、手動、Q&A、拡張処理 | ドキュメントパイプラインの自動チャンク分割 | Text Splitters；アプリケーションコードで組み立て |
| **検索 / リランク** | Milvus / FAISS / Chroma + BM25 / SPLADE / ColBERT / LTR / RRF；**13 種のリランカー** | セマンティック・全文・ハイブリッド検索；リランク設定可 | 複数リコール + 融合リランク | セマンティック・全文・ハイブリッド検索 + RRF + リランク | 複数のベクトル DB 検索 + 出典引用 | Retriever / reranker コンポーネント；自前で編成 |
| **ナレッジグラフ** | エンティティ・関係・イベント抽出；エンティティ解決、コミュニティ検出、マルチホップ検索 | ワークフロー・プラグイン・外部サービス経由で接続 | GraphRAG を内蔵 | ワークフローや外部サービス経由で接続 | エージェント / ツール経由で接続 | グラフ連携とカスタムチェーン |
| **エージェント / MCP** | LangGraph エージェント、Self-RAG / CRAG / FLARE；MCP クライアント / サーバー | Function Calling / ReAct エージェント、ツール、MCP | Agentic Workflow、MCP、コード実行 | Agent V2、ツール、MCP、VM 実行 | ノーコード Agent Builder、MCP、定期タスク | Agents / LangGraph / MCP；コードファースト |
| **可視化ワークフロー** | **汎用ノードキャンバスなし**；RAG デバッグ・ガバナンス画面・API に注力 | **中核機能**：アプリ / エージェントのノード編成 | エージェントと取り込みパイプラインの編成 | **中核機能**：フローノード編成 | ノーコード Agent Builder | 組み込みの製品 UI なし；アプリ側で実装 |
| **評価 / ガバナンス** | RAGAS、回帰ゲート、リーダーボード、有意差検定、エビデンス監査 | 実行ログ、可観測性、人手アノテーション | 検索テスト、チャンク検査、引用追跡 | 実行詳細、検索デバッグ、ログ | 出典引用；RAG 回帰ゲートは内蔵なし | LangSmith 連携または自前の評価基盤が必要 |
| **セーフティガード** | InputGuard / OutputGuard、PII / シークレットのマスキング、ホップごとの SSRF 検証 | モデレーションノードとワークフロールール | コード実行のサンドボックス；業務ガードは要設定 | ワークフローによるコンテンツ審査と VM サンドボックス | ローカルファースト、エージェントツール権限 | アプリのミドルウェアとデプロイ境界で実装 |
| **エンタープライズ権限 / コンプライアンス** | ドキュメント ACL + Security Trimming、RBAC、SCIM / SSO / SAML、監査 | ワークスペース権限；エンタープライズ版で組織と SSO | アカウントと API 認証；細粒度のコンプライアンスはデプロイ依存 | ABAC + RBAC；チーム・グループ・リソース権限 | Docker 版のマルチユーザー権限 | フレームワークは提供せず；アプリ側で実装 |
| **RAG デバッグ UI** | チャンクプレビュー、検索トレース、リランク過程、文単位の引用、KG、評価ダッシュボード | データセットテスト、ワークフロートレース、アプリログ | チャンク可視化、ヒット断片、引用 | ナレッジベーステスト、ワークフロー実行詳細 | ワークスペース、出典引用、チャット UI | 組み込み UI なし；可観測性プラットフォームを接続 |
| **Dify 外部ナレッジベース** | **Dify External Knowledge API にネイティブ対応** | 外部ナレッジベースをネイティブに消費 | API アダプターが必要 | API アダプターが必要 | API アダプターが必要 | アダプターを自前で実装 |
| **導入方法** | Docker Compose / Helm；完全なエンタープライズ RAG スタック | Docker Compose / Cloud | Docker Compose；公式推奨は 4C / 16 GB / 50 GB | Docker / Cloud | Desktop / Docker | Python / JS ライブラリ；アプリを自前で組み立て |

> この比較は各プロジェクトの公開版と公式ドキュメント（2026-07）に基づき、**リポジトリが直接提供する能力の表面**を示すもので、統一ベンチマークではありません。プラグイン、商用版、今後のリリースで結果が変わる可能性があります。

</details>

---

## 📍 実運用で検証済み

MimirQ は、7 つの地区レベルと 1 つの市レベルのナレッジベースにまたがる**市レベルの行政 Q&A アシスタント**で使われています。最新の直接検索の再測定では入力 SHA-256 `5a4c67...fac2` を用い、結果は次のとおりです。

| 最新結果（2026-07-24） | 結果 |
|:---|---:|
| 実行成功 | **800 / 800**、タイムアウト 0 |
| 正確 / 部分的に正確 / エビデンス不足 | **797 / 3 / 0** |
| 正確率 / 利用可能率 | **99.6% / 100%** |
| 平均 / P50 / P95 / P99 | **1.15s / 0.83s / 4.00s / 8.95s** |

今回の直接検索ではエビデンス条項カバレッジ 99.7% を達成しました。異なる embedding ランタイムをまたぐマルチナレッジベース検索は汎用の検索レイヤーがシャーディングして処理し、ドメイン固有のハードコードはありません。

独立した E2E 負荷テストでは、リランカーを有効化しリクエストごとにレスポンスキャッシュをバイパスした状態で、検索の並列度 3 で 12 リクエストの総時間を 41.46s から 30.14s に、会話の並列度 3 で 6 リクエストを 54.61s から 31.60s に短縮し、いずれもエラー 0 でした。並列化は単一リクエストのレイテンシを上げます。ここで検証しているのは同一バッチのスループット改善であり、ハードウェアの容量上限ではありません。

<details>
<summary><b>2026-07-24 の四方向・同一問題再測定を開く</b></summary>

同一の固定 800 問を、4 つの実際の連携経路で再測定しました。

<!-- データ出典：artifacts/changzhou_dify_4way_800_20260724/comparison_report.json（2026-07-24T04:02:01Z）；入力 SHA-256 5a4c67c42e8f8123774279d46af39ccc793da1b89fdea19a7359f63c8cb2fac2。 -->

| 経路 | 実行成功 | 正確率 / 利用可能率 | 回答条項カバレッジ | 回答のエビデンス裏付け | 誤エビデンス率 | 平均 / P50 / P95 |
|:---|---:|---:|---:|---:|---:|---:|
| **MimirQ 直接検索** | **800 / 800** | **99.6% / 100%** | **99.7%** | **99.8%** | 3.0% | **1.15s / 0.83s / 4.00s** |
| **Dify External → MimirQ** | **800 / 800** | 60.8% / 91.4% | 82.9% | **97.3%** | **2.7%** | 6.69s / 6.09s / 11.79s |
| **Dify HTTP → MimirQ** | **800 / 800** | **67.6% / 93.0%** | **85.6%** | 94.6% | 3.6% | 5.20s / 5.04s / 7.19s |
| **Dify ネイティブナレッジ** | **800 / 800** | 38.8% / 74.9% | 66.0% | 85.6% | 79.1% | 10.34s / 8.28s / 26.49s |

MimirQ の 2 つの Dify 経路の検索エビデンスカバレッジは 99.7% / 96.8% でしたが、生成回答の条項カバレッジは 82.9% / 85.6% でした。主な損失は知識のリコールではなく、ワークフローの回答生成で生じています。今回は 4 経路すべてで並列度 3 の 800 問を完全実行しました。Dify ネイティブナレッジは MimirQ を経由せず、初回の上流 Nginx 504 2 件は自動再試行で回復し、最終的に 800 / 800 が成功しました。

</details>

[完全な手法、指標の定義、過去の再測定](./docs/benchmarks/changzhou_dify.md) · [Dify の連携方式と実際のワークフロー](#-dify-連携)

---

## 📡 API リファレンス（OpenAPI / GitHub Pages）

| リソース | リンク / 説明 |
|:---|:---|
| **オンライン API ブラウザ（GitHub Pages）** | [https://skygazer42.github.io/MimirQ/](https://skygazer42.github.io/MimirQ/)（Redoc + 全量 `openapi.json`；fork 後は `https://<owner>.github.io/<repo>/` に変更） |
| **リポジトリガイド** | [docs/api/README.md](./docs/api/README.md)（認証、ベースパス、全 OpenAPI タグ対応表） |
| **シナリオ別フロー** | [docs/api/workflows.md](./docs/api/workflows.md) |
| **ローカル Swagger** | バックエンド起動後の [http://localhost:8000/docs](http://localhost:8000/docs) |
| **OpenAPI のエクスポート** | `make openapi-export` → `web/openapi.json` |
| **静的サイトのビルド** | `make api-docs-build` → `docs/api/site/` |

> 認証の規約：グローバルな認証ミドルウェアはありません。**すべてのルートが明示的に `get_current_account_id` に依存する必要があります**。テナントデータにアクセスするルートは `get_tenant_id` にも依存する必要があります。[backend_structure.md](./docs/backend_structure.md) を参照してください。

リポジトリで **Settings → Pages → GitHub Actions** を有効にしてください。`main` への push で [`.github/workflows/api-docs.yml`](./.github/workflows/api-docs.yml) が実行されます。

---

## 📦 デプロイ方法

ローカルでの試用から本番クラスタまで対応します。

| 方式 | コマンド | 説明 |
|:---:|:---|:---|
| **標準デプロイ** | `make up` | フルスタック：Postgres + Milvus + Etcd + MinIO + Redis + API + Worker |
| **標準 + フロントエンド** | `make up-web` | 初回起動に推奨；ローカル設定を初期化し完全な Web スタックを起動 |
| **軽量モード** | `make up-lite` | Milvus の代わりに Chroma/FAISS、MinIO 不要、素早い試用向け |
| **開発モード** | `make infra-up` | インフラのみ、バックエンド / フロントエンドをローカル実行 |
| **Helm / K8s** | `helm install` | 本番グレード、HPA、PDB、CronJob、PrometheusRule 付き |
| **パーサー拡張** | [起動コマンドを選択](./docs/quickstart.md) | 文書タイプに必要な CPU / GPU プロファイルだけを起動 |

<details>
<summary><b>本番デプロイのヒント</b></summary>

```bash
# .env を編集して本番パラメータを設定
# ENV=production
# AUTH_MODE=jwt
# SECRET_KEY=<32 文字以上のランダム文字列>
# POSTGRES_PASSWORD=<強いパスワード>

make up-prod
```

Kubernetes の本番デプロイについては [Helm デプロイガイド](./docs/deployment/helm.md) と [運用ハンドブック](./docs/deployment/runbook.md) を参照してください。

</details>

---

## 📖 機能ガイド

| ガイド | 説明 |
|:---|:---|
| [チャンクプレビュー](./docs/guides/chunk_preview.md) | ドキュメント分割の可視化とパラメータ調整 |
| [ナレッジグラフ](./docs/guides/knowledge_graph.md) | KG 抽出、可視化、RAG 強化 |
| [ドキュメント ACL](./docs/guides/document_acl.md) | ドキュメント単位のアクセス制御と Security Trimming |
| [URL インポート](./docs/guides/url_ingest.md) | リモート URL の取得と一括インポート |
| [ドキュメントバージョン](./docs/guides/document_versions.md) | パイプラインのバージョン管理とロールバック |
| [スパース検索](./docs/guides/sparse_retrieval.md) | SPLADE スパース検索チャネル |
| [ColBERT リランク](./docs/guides/reranking_colbert.md) | ColBERT レイトインタラクションのリランク |
| [RAG 最適化](./docs/guides/rag_optimization.md) | 検索と回答品質の最適化 |
| [検索トラブルシューティング](./docs/guides/retrieval_debugging.md) | 検索問題の診断 |
| [SAML SSO](./docs/guides/saml_sso.md) | SAML シングルサインオン連携 |
| [公開ベンチマーク](./docs/guides/public_benchmarks_zh.md) | 再現可能な中国語ベンチマーク（MIRACL-zh / CFEVER） |
| [API ガイド](./docs/api/README.md) | OpenAPI タグ対応表、Pages リンク、静的ビルド |
| [API ワークフロー](./docs/api/workflows.md) | シナリオ別のエンドポイント順序 |
| [API 総覧](./docs/API.md) | OpenAPI SSOT ナビゲーション・分割リファレンス・ハンドブックへの入口 |
| [クイックスタート](./docs/quickstart.md) | ソースからの開発 |
| [運用ハンドブック](./docs/deployment/runbook.md) | 本番運用とトラブルシューティング |

---

## ✅ 開発

push 前に CI と同一のチェックを実行してください（バックエンド + フロントエンド）。

```bash
# 完全チェック（バックエンド lint/test + フロントエンド lint/test）
make enterprise-checks

# バックエンドのみ
make verify && make test

# フロントエンドのみ
cd web && pnpm lint && pnpm test
```

---

## 🗺 ロードマップ

提供済みの機能は上記の比較表を参照してください。近日の予定：

- [ ] RAG 専用のデバッグ編成（汎用エージェントキャンバスではない）
- [ ] より多くのデータソースコネクタ（Confluence / S3 / Notion）
- [ ] 言語横断検索
- [ ] 統一 LLM-as-Judge（G-Eval + Self-Consistency）

> ロードマップは [GitHub Issues](https://github.com/skygazer42/MimirQ/issues) で公開追跡しています。機能要望・投票を歓迎します。

---

## 🤝 コントリビュート

タイポの修正、バグ報告、機能提案のいずれでも、まず [CONTRIBUTING.md](./.github/CONTRIBUTING.md) をお読みください。ローカル開発フローは[クイックスタート](./docs/quickstart.md)を参照し、push 前に `make enterprise-checks` を実行してください。

```bash
# フォークしてクローン
git clone https://github.com/<your-username>/MimirQ.git
cd MimirQ
make init

# ローカル開発
make infra-up           # インフラを起動
make models             # 固定バージョンの DeepDoc モデルをダウンロードして検証
cd web && pnpm dev      # フロントエンド開発
python main.py          # バックエンド開発

# push 前チェック
make enterprise-checks
```

---

## 📜 ライセンス

本プロジェクトは [Apache License 2.0](LICENSE) の下でライセンスされています。サードパーティコンポーネント（RAGFlow/DeepDoc から vendored したコード、およびビルド時にダウンロードされるモデルウェイトを含む）の帰属表示は [NOTICE](NOTICE) に記載されています。

> ⚠️ **PyMuPDF (AGPL-3.0) に関する注意**：デフォルトの PDF パースは PyMuPDF を使う場合があり、そのライセンスは AGPL-3.0 / 商用のデュアルライセンスです。本ソフトウェアを SaaS としてネットワーク越しに提供する場合、AGPL のネットワーク条項により、結合著作物全体のソース公開が求められる可能性があります。回避するには、寛容なライセンスのパース基盤（pypdf / pdfplumber）に切り替えてください。詳細は NOTICE を参照してください。

---

## 🙏 謝辞

MimirQ は優れたオープンソースエコシステムの上に構築されています。以下のプロジェクトに感謝します。

[Dify](https://github.com/langgenius/dify) · [RAGFlow](https://github.com/infiniflow/ragflow) · [FastAPI](https://fastapi.tiangolo.com/) · [LangChain](https://langchain.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [Milvus](https://milvus.io/) · [Next.js](https://nextjs.org/) · [PostgreSQL](https://www.postgresql.org/) · [RAGAS](https://docs.ragas.io/) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [MinerU](https://github.com/opendatalab/MinerU) · [Tailwind CSS](https://tailwindcss.com/) · [shadcn/ui](https://ui.shadcn.com/)

MimirQ の公開連携テストに CNY 50 の API 体験クレジットを提供してくださった [SiliconFlow](https://siliconflow.cn/) に感謝します。

---

<div align="center">

**MimirQ が、あなたの RAG を「動く」から「本番に出せる」に引き上げたなら、ぜひ ⭐ Star をお願いします！**

一つ一つの Star が、ブラックボックスを開き続ける私たちの原動力です。

[![Star History Chart](https://api.star-history.com/svg?repos=skygazer42/MimirQ&type=Date)](https://star-history.com/#skygazer42/MimirQ&Date)

</div>
