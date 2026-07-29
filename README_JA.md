<div align="center">

<img src="./images/logo.png" alt="MimirQ: 検査・回帰・ガバナンス可能なオープンソース RAG ナレッジベース" width="100%"/>

<p><b>フルスタックでオープンソース、中国語ファーストのエンタープライズ RAG ナレッジベース</b><br/>パース、ガバナンス、チャンク分割、検索、リランク、引用を、検査・差し替え・回帰検証できるナレッジパイプラインにします。</p>

<p>
  <a href="#mimirq-を作った理由"><b>なぜ MimirQ か</b></a> ·
  <a href="#プロダクト画面"><b>プロダクト画面</b></a> ·
  <a href="#クイックスタート"><b>クイックスタート</b></a> ·
  <a href="#dify-連携"><b>Dify 連携</b></a> ·
  <a href="#実運用での検証"><b>800問ベンチマーク</b></a>
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

## MimirQ を作った理由

**企業向けナレッジベースで本当に難しいのは、文書をベクトル化することではなく、誤りの所在を特定し、戦略を差し替え、品質を回帰検証できるようにすることです。**

MimirQ は、実際の行政ナレッジベース導入から生まれました。回答が誤ったとき、表を失ったパース、ルールを漏らしたガバナンス、意味を壊したチャンク分割、根拠を逃した検索、順位を誤ったリランク、引用から離れた生成のどこに原因があるかを判断する必要がありました。この流れを「アップロードして会話を開始」のボタンに隠すと、試作は速くても、長期運用の見積もり・受け入れ・統制が難しくなります。

> **制御可能なエンタープライズ・ナレッジパイプライン**
>
> `データ評価` → `パーサー選定` → `コンテンツ統制` → `業務単位のチャンク分割`<br/>→ `ベクトル / 全文索引` → `ハイブリッド検索` → `リランクと引用` → `Golden 回帰`

実案件は代表サンプルの評価から始めます。スキャンページ、画像、表、数式、レイアウトの複雑さを測り、パース品質と計算・レビューコストを確認します。複雑なレイアウトやスキャンには [MinerU](https://opendatalab.github.io/MinerU/) / [DeepDoc](https://github.com/infiniflow/ragflow/tree/main/deepdoc)、数式・表・版面構造が多い資料には [Docling](https://docling-project.github.io/docling/)、デジタル生成された Office 文書やプレーンテキストには [MarkItDown](https://github.com/microsoft/markitdown) などの軽量経路を候補にします。高リスクなコーパスには人手確認も必要です。

パース結果をスクリプト、ルール DSL、プラグインで統制した後、すべてに同じ固定長とオーバーラップを当てるのではなく、見出し、節、業務レコード、親子構造で分割します。索引では Milvus などのベクトルストアと BM25、ベクトル検索、リランクを組み合わせられます。上位アプリケーションは Dify、LangGraph、PydanticAI、または小さな API サービスでも構いません。

MimirQ は、すべてのプラットフォームを置き換えようとはしません。

- **単純で安定したローコード業務**では、Dify や RAGFlow の方が通常は速く導入できます。
- **DeepDoc と GraphRAG を一体で使いたい場合**、RAGFlow は成熟した選択肢です。
- **ナレッジ処理を差し替え・監査・回帰検証したい場合**、MimirQ はその能力をチャット業務から分離し、Dify の外部ナレッジ層としても利用できます。

現在のリポジトリは 30 のパース基盤、86 種のチャンク戦略、13 系統のリランカー、固定 800 問の評価履歴を備えています。数は幅を示すだけで、目的は各段階の検査、引用と版の追跡、Golden セットによるリリース保護です。詳細は[エンタープライズ・ナレッジパイプライン設計原則](./docs/guides/rag_platform_design_principles.md)を参照してください。

---

## プロダクト画面

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

## クイックスタート

### 前提条件

- [Docker](https://docs.docker.com/get-docker/) 20.10+ & [Docker Compose](https://docs.docker.com/compose/install/) 2.0+
- GNU Make。Docker 起動ではローカル設定の生成に Python 3.9+ も必要
- ソース開発モードでは Python 3.11+、Node.js 20+、pnpm 10.26 も必要
- 最低 4 CPU コア / 16 GB RAM / 50 GB ディスク

### 初期化

```bash
git clone --depth 1 --single-branch https://github.com/skygazer42/MimirQ.git
cd MimirQ
make init
```

`make init` は不足している `.env` と `web/.env.local` だけを作成し、既存値は上書きしません。`.env` にはデプロイ方式に応じて次の項目を設定します。

- デフォルトモデル：`LLM_API_KEY`（必須）
- カスタム LLM：`LLM_API_BASE`、`LLM_MODEL`
- 独立 Embedding：`EMBEDDING_API_BASE`、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL`
- Reranker：`ENABLE_RERANKER`、`RERANKER_API_BASE`、`RERANKER_API_KEY`、`RERANKER_MODEL`
- 初期管理者：`INITIAL_ADMIN_EMAIL`、`INITIAL_ADMIN_USERNAME`、`INITIAL_ADMIN_PASSWORD`

設定値と初期化ルールは[モデルサービスと初期管理者の設定](./docs/guides/model_services.md)を参照してください。

| 起動方法 | 用途 | アプリの実行場所 |
|:---|:---|:---|
| **Docker 一括起動（推奨）** | 初回利用、サーバーデプロイ | Web、API、Worker、依存サービスをコンテナで実行 |
| **ソース開発** | フロントエンド・バックエンド開発、ホットリロード | `.venv` + pip で API、pnpm で Web、Docker で基盤を実行 |

### 方法 1：Docker で一括起動

```bash
make up-web
make api-ping
```

[http://localhost:3000](http://localhost:3000) にアクセスします。初期管理者を設定していない場合は、画面で最初のアカウントを登録します。初回ビルド、プロキシ、本番用シークレット、ネットワーク設定は [Docker Compose ガイド](./docs/deployment/docker_compose.md)を参照してください。

停止は `make down`、永続データの削除は `make docker-reset`、このプロジェクトのサービスイメージも含めた削除は `make docker-purge` を使用します。MimirQ は独立した Compose プロジェクト名 `mimirq` を使用するため、同じホストの Dify は削除対象になりません。後者 2 つは元に戻せません。PowerShell、所有関係の確認、旧データ移行、復旧、正確な対象範囲は [Docker Compose ガイド](./docs/deployment/docker_compose.md)を参照してください。

### 方法 2：ソース開発（Python venv + pip + pnpm）

これは一般的なローカル開発方式で、Conda は不要です。FastAPI は Python `.venv`、Next.js は pnpm で実行し、Docker は PostgreSQL、Redis、Milvus などの基盤だけに使用します。

```bash
make setup-host
```

`make setup-host` は `.venv` の作成、pip / pnpm 依存関係のインストール、パーサーモデルの準備、Docker 基盤の起動を行います。デフォルトでは 2 つのターミナルを使用します。

```bash
# ターミナル 1：FastAPI（ホットリロード）
make backend

# ターミナル 2：Next.js（ホットリロード）
make web
```

独立 Worker の設定は[モデルサービスと初期管理者の設定](./docs/guides/model_services.md)を参照してください。ホスト側のサービスを確認します。

```bash
make api-ping
```

ホストプロセスを終了した後、`make infra-down` で依存サービスを停止します。

### サービス URL

| サービス | URL |
|:---:|:---|
| **フロントエンド UI** | [http://localhost:3000](http://localhost:3000) |
| **API ドキュメント** | [http://localhost:8000/docs](http://localhost:8000/docs) |

> 軽量構成には `make up-lite` を使用し、UI が必要な場合は別途 `make web` を実行します。

モデル、パーサー、プロキシ、Windows の詳細は[開発ガイド](./docs/quickstart.md)、公開サンプルは[プラグインガイド](./plugins/pipelines/changzhou-gov-service-knowledge/README.md)を参照してください。

---

## Dify 連携

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

Dify 標準の外部ナレッジベースエンドポイントは `POST /api/v1/integrations/dify/retrieval` です。`POST /api/v1/integrations/dify/conversation-turns` は、回答・引用・会話識別子の返送に使用できます。設定は [`.env.example`](./.env.example)、デプロイ前の検証は [readiness gate](./scripts/README.md)、実測結果は[実運用での検証](#実運用での検証)を参照してください。

---

## 主要機能の比較

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

## 実運用での検証

MimirQ は、7 つの地区レベルと 1 つの市レベルのナレッジベースにまたがる**市レベルの行政 Q&A アシスタント**で使われています。2026-07-27 に同じ固定 800 問を実セルフホストモデルで再測定し、5 経路すべてが最終的に **800 / 800** を完了しました。

<!-- データ出典：artifacts/dify_4way_800_20260727/comparison_report.json、artifacts/dify_4way_800_20260727/summary_for_sharing.md、artifacts/changzhou_local_3model_800_20260727/summary.json；入力 SHA-256 5a4c67c42e8f8123774279d46af39ccc793da1b89fdea19a7359f63c8cb2fac2。 -->

> **「検索コア」は LLM 問答ではありません。** Embedding、ハイブリッド検索、リランクを実行して Top-K エビデンスを直接返します。「RAG 生成」で初めて LLM が回答を生成します。

### 検索コア（LLM 生成なし）

| エビデンス経路 | 正確率 | 利用可能率 | エビデンスカバレッジ | レイテンシ（平均 / P95） |
|:---|---:|---:|---:|---:|
| **MimirQ 検索コア** | **98.9%** | **100%** | **99.5%** | **3.64s / 12.58s** |

### エンドツーエンド回答（LLM 生成あり）

| 回答経路 | 正確率 | 利用可能率 | カバレッジ（エビデンス / 回答） | レイテンシ（平均 / P95） |
|:---|---:|---:|---:|---:|
| **MimirQ RAG 生成** | **90.9%** | **100%** | **99.7% / 96.6%** | **2.59s / 8.15s** |
| **Dify HTTP → MimirQ** | 64.3% | 92.1% | 96.3% / 83.6% | 13.15s / 17.33s |
| **Dify External → MimirQ** | 62.7% | 91.7% | **99.7%** / 83.8% | 12.14s / 23.49s |
| **Dify ネイティブナレッジ¹** | 38.6% | 74.5% | 83.8% / 66.1% | 13.67s / 29.55s |

¹ Dify ネイティブナレッジは MimirQ を経由しません。正確・部分正確・エビデンス不足の件数は詳細レポートを参照してください。

Dify HTTP / External の検索エビデンスカバレッジは 96.3% / 99.7%、生成回答の条項カバレッジは 83.6% / 83.8% でした。主な損失は MimirQ の検索ではなく、Dify の回答生成で生じています。

<details>
<summary><b>テスト境界、並列性、汎用性の説明</b></summary>

- 検索コアはエビデンスを返し、他の 4 経路は生成回答を返します。2 表の正確率とレイテンシは同一タスクとして直接比較できません。
- 検索の並列度 5 では初回に設定済み admission backpressure が 15 件発生しました。並列度 3 で該当問題だけを再試行し、800 / 800 に復旧しました。
- MimirQ には地域・事項・問題の特別扱いはありません。異なる Embedding ランタイムをまたぐマルチナレッジベース要求は汎用検索レイヤーがシャーディングします。

</details>

[完全な手法、指標の定義、過去の再測定](./docs/benchmarks/changzhou_dify.md) · [Dify の連携方式と実際のワークフロー](#dify-連携)

---

## デプロイ方法

次のデプロイ方式をサポートします。

| 方式 | コマンド | 説明 |
|:---:|:---|:---|
| **標準デプロイ** | `make up` | フルスタック：Postgres + Milvus + Etcd + MinIO + Redis + API + Worker |
| **標準 + フロントエンド** | `make up-web` | 初回起動に推奨；ローカル設定を初期化し完全な Web スタックを起動 |
| **軽量モード** | `make up-lite` | Milvus の代わりに Chroma/FAISS、MinIO 不要、素早い試用向け |
| **開発モード** | `make infra-up` | インフラのみ、バックエンド / フロントエンドをローカル実行 |
| **Helm / K8s** | `helm install` | 本番グレード、HPA、PDB、CronJob、PrometheusRule 付き |
| **パーサー拡張** | [Docker Compose ガイド](./docs/deployment/docker_compose.md) | 必要な CPU / GPU プロファイルを起動 |

本番設定とアップグレード手順は [Docker Compose ガイド](./docs/deployment/docker_compose.md)、[Helm デプロイガイド](./docs/deployment/helm.md)、[運用ハンドブック](./docs/deployment/runbook.md)を参照してください。

---

## 機能ガイド

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
| [クイックスタート](./docs/quickstart.md) | ソースからの開発 |
| [運用ハンドブック](./docs/deployment/runbook.md) | 本番運用とトラブルシューティング |

---

## 開発

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

## ロードマップ

提供済みの機能は上記の比較表を参照してください。近日の予定：

- [ ] RAG 専用のデバッグ編成（汎用エージェントキャンバスではない）
- [ ] より多くのデータソースコネクタ（Confluence / S3 / Notion）
- [ ] 言語横断検索
- [ ] 統一 LLM-as-Judge（G-Eval + Self-Consistency）

> ロードマップ、機能要望、投票は [GitHub Issues](https://github.com/skygazer42/MimirQ/issues) で管理します。

---

## コントリビュート

コードの提供、問題報告、機能提案の前に [CONTRIBUTING.md](./.github/CONTRIBUTING.md) を参照してください。ローカル開発フローは[クイックスタート](./docs/quickstart.md)に記載しています。push 前に `make enterprise-checks` を実行してください。

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

## ライセンス

本プロジェクトは [Apache License 2.0](LICENSE) の下でライセンスされています。サードパーティコンポーネント（RAGFlow/DeepDoc から vendored したコード、およびビルド時にダウンロードされるモデルウェイトを含む）の帰属表示は [NOTICE](NOTICE) に記載されています。

> **PyMuPDF (AGPL-3.0) に関する注意**：デフォルトの PDF パースは PyMuPDF を使う場合があり、そのライセンスは AGPL-3.0 / 商用のデュアルライセンスです。本ソフトウェアを SaaS としてネットワーク越しに提供する場合、AGPL のネットワーク条項により、結合著作物全体のソース公開が求められる可能性があります。この制約を避ける場合は、寛容なライセンスのパース基盤（pypdf / pdfplumber）に切り替えてください。詳細は NOTICE を参照してください。

---

## 謝辞

MimirQ は優れたオープンソースエコシステムの上に構築されています。以下のプロジェクトに感謝します。

[Dify](https://github.com/langgenius/dify) · [RAGFlow](https://github.com/infiniflow/ragflow) · [FastAPI](https://fastapi.tiangolo.com/) · [LangChain](https://langchain.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [Milvus](https://milvus.io/) · [Next.js](https://nextjs.org/) · [PostgreSQL](https://www.postgresql.org/) · [RAGAS](https://docs.ragas.io/) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [MinerU](https://github.com/opendatalab/MinerU) · [Tailwind CSS](https://tailwindcss.com/) · [shadcn/ui](https://ui.shadcn.com/)

---

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=skygazer42/MimirQ&type=Date)](https://star-history.com/#skygazer42/MimirQ&Date)

</div>
