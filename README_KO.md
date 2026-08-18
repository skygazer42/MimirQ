<div align="center">

<img src="./docs/images/banner.svg" alt="MimirQ: 검사·회귀·거버넌스가 가능한 오픈소스 RAG 지식베이스" width="100%"/>

<p><b>풀스택 오픈소스, 중국어 우선 엔터프라이즈 RAG 지식베이스</b><br/>파싱, 거버넌스, 청킹, 검색, 리랭킹, 인용을 검사·교체·회귀 검증할 수 있는 지식 파이프라인으로 만듭니다.</p>

<p>
  <a href="#mimirq를-만든-이유"><b>왜 MimirQ인가</b></a> ·
  <a href="#제품-화면"><b>제품 화면</b></a> ·
  <a href="#빠른-시작"><b>빠른 시작</b></a> ·
  <a href="#dify-연동"><b>Dify 연동</b></a> ·
  <a href="#운영-환경-검증"><b>800문항 벤치마크</b></a>
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

## MimirQ를 만든 이유

**기업 지식베이스에서 어려운 일은 문서를 벡터화하는 것이 아니라, 오류를 찾아내고 전략을 교체하며 품질 회귀가 없음을 증명하는 것입니다.**

MimirQ는 실제 행정 지식베이스 구축에서 시작되었습니다. 답변이 틀렸을 때 표를 놓친 파싱, 규칙을 누락한 거버넌스, 의미를 훼손한 청킹, 근거를 놓친 검색, 순서를 잘못 정한 리랭킹, 인용에서 벗어난 생성 중 어디가 원인인지 판단해야 했습니다. 이 경로를 “업로드 후 채팅” 버튼 뒤에 숨기면 프로토타입은 빨라지지만 장기 구축의 견적, 검수, 통제가 어려워집니다.

> **통제 가능한 엔터프라이즈 지식 파이프라인**
>
> `데이터 평가` → `파서 선택` → `콘텐츠 거버넌스` → `업무 단위 청킹`<br/>→ `벡터 / 키워드 인덱스` → `하이브리드 검색` → `리랭킹과 인용` → `Golden 회귀`

실제 프로젝트는 대표 샘플 평가부터 시작합니다. 스캔 페이지, 이미지, 표, 수식, 레이아웃 복잡도를 측정하고 파싱 품질과 연산·검수 비용을 확인합니다. 복잡한 레이아웃이나 스캔 문서는 [MinerU](https://opendatalab.github.io/MinerU/) / [DeepDoc](https://github.com/infiniflow/ragflow/tree/main/deepdoc), 수식·표·판면 구조가 많은 자료는 [Docling](https://docling-project.github.io/docling/), 디지털 원본 Office 문서나 일반 텍스트는 [MarkItDown](https://github.com/microsoft/markitdown) 같은 경량 경로를 후보로 평가합니다. 고위험 코퍼스에는 사람의 검수도 필요합니다.

파싱 결과를 스크립트, 규칙 DSL, 플러그인으로 관리한 뒤 모든 문서에 같은 고정 길이와 오버랩을 적용하지 않고 제목, 절, 업무 레코드, 부모-자식 구조에 맞춰 청킹합니다. 인덱스는 Milvus 같은 벡터 저장소와 BM25, 벡터 검색, 리랭킹을 조합할 수 있습니다. 상위 애플리케이션은 Dify, LangGraph, PydanticAI 또는 작은 API 서비스여도 됩니다.

MimirQ는 모든 플랫폼을 대체하려 하지 않습니다.

- **단순하고 안정적인 로우코드 업무**에는 Dify나 RAGFlow가 일반적으로 더 빠른 선택입니다.
- **DeepDoc과 GraphRAG를 통합해서 사용하려는 경우** RAGFlow는 성숙한 선택지입니다.
- **지식 처리 경로를 교체·감사·회귀 검증해야 하는 경우** MimirQ는 이 능력을 채팅 업무와 분리하고 Dify의 외부 지식 계층으로도 제공합니다.

현재 저장소는 30개 파싱 백엔드, 86개 청킹 전략, 13개 리랭커 계열, 고정 800문항 평가 기록을 제공합니다. 숫자는 범위를 보여줄 뿐이며, 목표는 각 단계를 검사하고 인용과 버전을 추적하며 Golden 세트로 릴리스를 보호하는 것입니다. 자세한 내용은 [엔터프라이즈 지식 파이프라인 설계 원칙](./docs/guides/rag_platform_design_principles.md)을 참고하십시오.

---

## 제품 화면

아래 화면은 리포지토리에 포함된 공개 행정 서비스 플러그인 샘플로 생성했습니다. 운영 지식베이스 데이터는 포함되어 있지 않습니다.

<table>
  <tr>
    <td colspan="2" align="center">
      <img src="./docs/images/screenshots/knowledge-graph.png" alt="MimirQ 지식 그래프 화면" width="100%"/>
      <br/><strong>지식 그래프</strong>
      <br/><sub>엔티티·이벤트·관계를 하나의 캔버스에서 검색·분석.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/dataset-management.png" alt="MimirQ 지식베이스 관리 화면" width="100%"/>
      <br/><strong>지식베이스 관리</strong>
      <br/><sub>데이터셋·문서·청크·수집 상태를 한곳에서 파악.</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/rag-evaluation.png" alt="MimirQ 골든 회귀 평가 화면" width="100%"/>
      <br/><strong>골든 회귀 평가</strong>
      <br/><sub>표준 Q&A, 실행 기록, Recall / MRR 등의 지표를 같은 화면에서 확인.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/settings.png" alt="MimirQ 시스템 설정 화면" width="100%"/>
      <br/><strong>시스템 설정</strong>
      <br/><sub>의존성 상태, 파싱 능력, 모델 서비스 연동을 한곳에서 확인.</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/chat-history.png" alt="MimirQ 대화 기록 및 근거 확인 화면" width="100%"/>
      <br/><strong>대화 기록 및 근거 확인</strong>
      <br/><sub>지난 세션을 검색하고 완전한 답변·출처·피드백 경로를 되짚기.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/ingestion-monitor.png" alt="MimirQ 수집 실행 모니터" width="100%"/>
      <br/><strong>수집 실행 모니터</strong>
      <br/><sub>데이터셋별로 파싱·청킹·거버넌스·내보내기·재시도 상태를 관찰.</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/data-governance.png" alt="MimirQ 데이터 거버넌스 워크벤치" width="100%"/>
      <br/><strong>데이터 거버넌스</strong>
      <br/><sub>문서 미리보기·품질 검사·정제·주석을 하나의 워크벤치에서.</sub>
    </td>
  </tr>
</table>

---

## 빠른 시작

### 사전 요구 사항

- [Docker](https://docs.docker.com/get-docker/) 20.10+ & [Docker Compose](https://docs.docker.com/compose/install/) 2.0+
- GNU Make. Docker 시작에는 로컬 설정 생성을 위한 Python 3.9+도 필요
- 소스 개발 모드에는 Python 3.11+, Node.js 20+, pnpm 10.26도 필요
- 최소 4 CPU 코어 / 16 GB RAM / 50 GB 디스크

### 초기화

```bash
git clone --depth 1 --single-branch https://github.com/skygazer42/MimirQ.git
cd MimirQ
make init
```

`make init`는 누락된 `.env`와 `web/.env.local`만 만들며 기존 값은 덮어쓰지 않습니다. `.env`에는 배포 방식에 따라 다음 항목을 설정합니다.

- 기본 모델: `LLM_API_KEY`(필수)
- 사용자 지정 LLM: `LLM_API_BASE`, `LLM_MODEL`
- 독립 Embedding: `EMBEDDING_API_BASE`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`
- Reranker: `ENABLE_RERANKER`, `RERANKER_API_BASE`, `RERANKER_API_KEY`, `RERANKER_MODEL`
- 초기 관리자: `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_USERNAME`, `INITIAL_ADMIN_PASSWORD`

설정값과 초기화 규칙은 [모델 서비스 및 초기 관리자 설정](./docs/guides/model_services.md)을 참조하세요.

| 시작 방식 | 용도 | 애플리케이션 실행 위치 |
|:---|:---|:---|
| **Docker 일괄 시작(권장)** | 첫 사용, 서버 배포 | 웹, API, 워커, 의존 서비스를 컨테이너에서 실행 |
| **소스 개발** | 프런트엔드·백엔드 개발, 핫 리로드 | `.venv` + pip로 API, pnpm으로 웹, Docker로 인프라 실행 |

### 방법 1: Docker로 일괄 시작

```bash
make up-web
make api-ping
```

[http://localhost:3000](http://localhost:3000)에 접속합니다. 초기 관리자를 설정하지 않았다면 화면에서 첫 계정을 등록하세요. 첫 빌드, 프록시, 운영 시크릿, 네트워크 설정은 [Docker Compose 가이드](./docs/deployment/docker_compose.md)를 참조하세요.

중지에는 `make down`, 영구 데이터 삭제에는 `make docker-reset`, 이 프로젝트의 서비스 이미지까지 삭제하려면 `make docker-purge`를 사용합니다. MimirQ는 독립된 Compose 프로젝트 이름 `mimirq`를 사용하므로 같은 호스트의 Dify는 정리 대상이 아닙니다. 마지막 두 명령은 되돌릴 수 없습니다. PowerShell 명령, 소유 관계 확인, 기존 데이터 이전, 복구 및 정확한 범위는 [Docker Compose 가이드](./docs/deployment/docker_compose.md)를 참조하세요.

### 방법 2: 소스 개발(Python venv + pip + pnpm)

일반적인 로컬 개발 방식으로 Conda는 필요하지 않습니다. FastAPI는 Python `.venv`, Next.js는 pnpm으로 실행하고 Docker는 PostgreSQL, Redis, Milvus 같은 인프라에만 사용합니다.

```bash
make setup-host
```

`make setup-host`는 `.venv` 생성, pip / pnpm 의존성 설치, 파서 모델 준비, Docker 인프라 시작을 수행합니다. 기본 구성에서는 터미널 두 개를 사용합니다.

```bash
# 터미널 1: FastAPI(핫 리로드)
make backend

# 터미널 2: Next.js(핫 리로드)
make web
```

독립 Worker 설정은 [모델 서비스 및 초기 관리자 설정](./docs/guides/model_services.md)을 참조하세요. 호스트 서비스를 확인합니다.

```bash
make api-ping
```

호스트 프로세스가 모두 종료되면 `make infra-down`으로 의존 서비스를 중지합니다.

### 서비스 URL

| 서비스 | URL |
|:---:|:---|
| **프런트엔드 UI** | [http://localhost:3000](http://localhost:3000) |
| **API 문서** | [http://localhost:8000/docs](http://localhost:8000/docs) |

> 경량 구성에는 `make up-lite`를 사용하고, UI가 필요하면 `make web`을 별도로 실행합니다.

모델, 파서, 프록시, Windows 세부 절차는 [개발 가이드](./docs/quickstart.md), 공개 샘플은 [플러그인 가이드](./plugins/pipelines/changzhou-gov-service-knowledge/README.md)를 참조하세요.

---

## Dify 연동

MimirQ는 워크플로 캔버스를 다시 구현하지 않고도, 거버넌스가 가능한 RAG 레이어로 기존 Dify 앱에 연결할 수 있습니다. 현재 두 가지 방식을 지원합니다.

- **External Knowledge API**: Dify가 오케스트레이션과 생성을 담당하고, MimirQ가 문서 거버넌스·검색·리랭크·권한 필터링·근거 반환을 담당합니다.
- **Workflow HTTP 노드**: Dify가 커스텀 라우팅과 파라미터를 담당하고, MimirQ가 지정된 지식 범위에 대해 근거와 트레이스를 반환합니다.

### Workflow HTTP 노드

<p align="center">
  <a href="./docs/images/screenshots/dify-mimirq-http-workflow.png">
    <img src="./docs/images/screenshots/dify-mimirq-http-workflow.png" alt="Dify HTTP 노드가 MimirQ 검색 API를 호출하고 근거를 병합" width="1100" style="max-width: 100%; height: auto;"/>
  </a>
  <br/>
  <sub>실제 Dify HTTP 서브체인(마스킹됨): JSON 요청을 안전하게 구성 → HTTP 노드가 MimirQ retrieval 엔드포인트 호출 → 결과 변환 → 지식 근거 병합.</sub>
</p>

### External Knowledge API

<p align="center">
  <a href="./docs/images/screenshots/dify-mimirq-workflow.png">
    <img src="./docs/images/screenshots/dify-mimirq-workflow.png" alt="Dify 워크플로가 지역 라우팅으로 여덟 개의 MimirQ 행정 지식베이스에 연결" width="560" style="max-width: 100%; height: auto;"/>
  </a>
  <br/>
  <sub>실제 Dify Chatflow(마스킹됨): 초록색 지식 검색 노드가 External Knowledge API로 MimirQ를 호출한 뒤 근거를 통일적으로 병합; 클릭하면 원본 이미지.</sub>
</p>

> 그림의 지역 라우팅은 선택적 샘플 플러그인에서 온 것입니다. MimirQ 코어는 지역·항목·업종 규칙을 내장하지 않습니다.

Dify 표준 외부 지식베이스 엔드포인트는 `POST /api/v1/integrations/dify/retrieval`입니다. `POST /api/v1/integrations/dify/conversation-turns`는 답변·인용·대화 식별자 회신에 사용할 수 있습니다. 설정은 [`.env.example`](./.env.example), 배포 전 검증은 [readiness gate](./scripts/README.md), 실측 결과는 [운영 환경 검증](#운영-환경-검증)을 참조하세요.

---

## 핵심 기능 비교

<details>
<summary><b>Dify, RAGFlow, FastGPT, AnythingLLM, LangChain과의 기능 비교 펼치기</b></summary>


| 기능 영역 | **MimirQ** | [Dify](https://github.com/langgenius/dify) | [RAGFlow](https://github.com/infiniflow/ragflow) | [FastGPT](https://github.com/labring/FastGPT) | [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | [LangChain](https://github.com/langchain-ai/langchain) |
|:---|:---|:---|:---|:---|:---|:---|
| **문서 파싱** | **30 파싱 백엔드**: PDF, OCR, 레이아웃, 표, 수식, VLM | Knowledge Pipeline; PDF, PPT 등 일반 형식 | **DeepDoc**; 복잡한 레이아웃과 스캔; MinerU / Docling | PDF·스캔·표·수식을 Markdown으로 변환 | PDF, TXT, DOCX 등 문서 파이프라인 | Document Loaders와 서드파티 파서 연동 |
| **청킹** | **86종 전략**: 재귀, 시맨틱, 부모-자식, RAPTOR, Late Chunking; 시각화 미리보기 | 범용, 부모-자식, Q&A, 파이프라인 정의 처리 | 템플릿 기반 청킹; 시각화된 수작업 개입 | 자동, 수동, Q&A, 강화 처리 | 문서 파이프라인 자동 청킹 | Text Splitters; 애플리케이션 코드로 조합 |
| **검색 / 리랭크** | Milvus / FAISS / Chroma + BM25 / SPLADE / ColBERT / LTR / RRF; **13종 리랭커** | 시맨틱·전문·하이브리드 검색; 리랭크 설정 가능 | 다중 리콜 + 융합 리랭크 | 시맨틱·전문·하이브리드 검색 + RRF + 리랭크 | 여러 벡터 DB 검색 + 출처 인용 | Retriever / reranker 컴포넌트; 직접 구성 |
| **지식 그래프** | 엔티티·관계·이벤트 추출; 엔티티 해소, 커뮤니티 탐지, 멀티홉 검색 | 워크플로·플러그인·외부 서비스로 연결 | GraphRAG 내장 | 워크플로나 외부 서비스로 연결 | 에이전트 / 툴로 연결 | 그래프 연동과 커스텀 체인 |
| **에이전트 / MCP** | LangGraph 에이전트, Self-RAG / CRAG / FLARE; MCP 클라이언트 / 서버 | Function Calling / ReAct 에이전트, 툴, MCP | Agentic Workflow, MCP, 코드 실행기 | Agent V2, 툴, MCP, VM 실행 | 노코드 Agent Builder, MCP, 예약 작업 | Agents / LangGraph / MCP; 코드 우선 |
| **시각화 워크플로** | **범용 노드 캔버스 없음**; RAG 디버깅·거버넌스 화면·API에 집중 | **핵심 기능**: 앱 / 에이전트 노드 편성 | 에이전트와 수집 파이프라인 편성 | **핵심 기능**: 플로 노드 편성 | 노코드 Agent Builder | 내장 제품 UI 없음; 애플리케이션이 구현 |
| **평가 / 거버넌스** | RAGAS, 회귀 게이트, 리더보드, 유의성 검정, 근거 감사 | 실행 로그, 관측성, 수작업 주석 | 검색 테스트, 청크 검사, 인용 추적 | 실행 상세, 검색 디버깅, 로그 | 출처 인용; 내장 RAG 회귀 게이트 없음 | LangSmith 연동 또는 자체 평가 스택 필요 |
| **세이프티 가드** | InputGuard / OutputGuard, PII / 시크릿 마스킹, 홉별 SSRF 검증 | 모더레이션 노드와 워크플로 규칙 | 코드 실행 샌드박스; 비즈니스 가드는 설정 필요 | 워크플로 기반 콘텐츠 심사와 VM 샌드박스 | 로컬 우선, 에이전트 툴 권한 | 애플리케이션 미들웨어와 배포 경계로 구현 |
| **엔터프라이즈 권한 / 컴플라이언스** | 문서 ACL + Security Trimming, RBAC, SCIM / SSO / SAML, 감사 | 워크스페이스 권한; 엔터프라이즈 판에서 조직과 SSO | 계정과 API 인증; 세분화된 컴플라이언스는 배포 종속 | ABAC + RBAC; 팀·그룹·리소스 권한 | Docker 판 멀티유저 권한 | 프레임워크가 제공하지 않음; 애플리케이션이 구현 |
| **RAG 디버깅 UI** | 청크 미리보기, 검색 트레이스, 리랭크 과정, 문장 인용, KG, 평가 대시보드 | 데이터셋 테스트, 워크플로 트레이스, 앱 로그 | 청크 시각화, 히트 조각, 인용 | 지식베이스 테스트, 워크플로 실행 상세 | 워크스페이스, 출처 인용, 채팅 UI | 내장 UI 없음; 관측 플랫폼 연결 |
| **Dify 외부 지식베이스** | **Dify External Knowledge API 네이티브 호환** | 외부 지식베이스를 네이티브로 소비 | API 어댑터 필요 | API 어댑터 필요 | API 어댑터 필요 | 어댑터를 직접 구현 |
| **시작 방식** | Docker Compose / Helm; 완전한 엔터프라이즈 RAG 스택 | Docker Compose / Cloud | Docker Compose; 공식 권장 4C / 16 GB / 50 GB | Docker / Cloud | Desktop / Docker | Python / JS 라이브러리; 애플리케이션을 직접 조립 |

> 이 비교는 각 프로젝트의 공개 버전과 공식 문서(2026-07)를 기반으로 하며, **리포지토리가 직접 제공하는 능력 표면**을 설명하는 것이지 통일된 벤치마크가 아닙니다. 플러그인, 상용 판, 이후 릴리스에 따라 개별 항목이 달라질 수 있습니다.

</details>

---

## 운영 환경 검증

MimirQ는 7개 구역 단위와 1개 시 단위 지식베이스에 걸친 **시 단위 행정 Q&A 어시스턴트**에 사용되고 있습니다. 2026-07-27에 동일한 고정 800문항을 실제 셀프호스팅 모델로 재측정했으며, 다섯 경로 모두 최종 **800 / 800**을 완료했습니다.

<!-- 데이터 출처: artifacts/dify_4way_800_20260727/comparison_report.json, artifacts/dify_4way_800_20260727/summary_for_sharing.md, artifacts/changzhou_local_3model_800_20260727/summary.json; 입력 SHA-256 5a4c67c42e8f8123774279d46af39ccc793da1b89fdea19a7359f63c8cb2fac2. -->

> **“검색 코어”는 LLM 질의응답이 아닙니다.** Embedding, 하이브리드 검색, 리랭킹을 수행한 뒤 Top-K 근거를 직접 반환합니다. “RAG 생성” 단계에서 LLM이 답변을 만듭니다.

### 검색 코어(LLM 생성 제외)

| 근거 경로 | 정확률 | 사용 가능률 | 근거 커버리지 | 지연(평균 / P95) |
|:---|---:|---:|---:|---:|
| **MimirQ 검색 코어** | **98.9%** | **100%** | **99.5%** | **3.64s / 12.58s** |

### 엔드투엔드 답변(LLM 생성 포함)

| 답변 경로 | 정확률 | 사용 가능률 | 커버리지(근거 / 답변) | 지연(평균 / P95) |
|:---|---:|---:|---:|---:|
| **MimirQ RAG 생성** | **90.9%** | **100%** | **99.7% / 96.6%** | **2.59s / 8.15s** |
| **Dify HTTP → MimirQ** | 64.3% | 92.1% | 96.3% / 83.6% | 13.15s / 17.33s |
| **Dify External → MimirQ** | 62.7% | 91.7% | **99.7%** / 83.8% | 12.14s / 23.49s |
| **Dify 네이티브 지식¹** | 38.6% | 74.5% | 83.8% / 66.1% | 13.67s / 29.55s |

¹ Dify 네이티브 지식은 MimirQ를 사용하지 않습니다. 정확, 부분 정확, 근거 부족 문항 수는 상세 보고서를 참조하세요.

Dify HTTP / External의 검색 근거 커버리지는 96.3% / 99.7%, 생성 답변 조항 커버리지는 83.6% / 83.8%였습니다. 주요 손실은 MimirQ 검색이 아니라 Dify 답변 생성에서 발생합니다.

<details>
<summary><b>테스트 경계, 동시성, 범용성 설명</b></summary>

- 검색 코어는 근거를 반환하고 다른 네 경로는 생성 답변을 반환합니다. 두 표의 정확률과 지연은 동일 작업으로 직접 비교할 수 없습니다.
- 검색 동시성 5에서 첫 실행에 설정된 admission backpressure 15건이 발생했습니다. 동시성 3으로 해당 문항만 재시도해 800 / 800으로 복구했습니다.
- MimirQ에는 지역·항목·문항별 특수 처리가 없습니다. 서로 다른 Embedding 런타임을 사용하는 다중 지식베이스 요청은 범용 검색 계층에서 샤딩합니다.

</details>

[전체 방법론, 지표 정의, 과거 재측정](./docs/benchmarks/changzhou_dify.md) · [Dify 연동 방식과 실제 워크플로](#dify-연동)

---

## 배포 방식

다음 배포 방식을 지원합니다.

| 방식 | 명령 | 설명 |
|:---:|:---|:---|
| **표준 배포** | `make up` | 풀스택: Postgres + Milvus + Etcd + MinIO + Redis + API + Worker |
| **표준 + 프런트엔드** | `make up-web` | 첫 기동에 권장; 로컬 설정을 초기화하고 완전한 웹 스택 기동 |
| **경량 모드** | `make up-lite` | Milvus 대신 Chroma/FAISS, MinIO 불필요, 빠른 체험용 |
| **개발 모드** | `make infra-up` | 인프라만; 백엔드 / 프런트엔드를 로컬 실행 |
| **Helm / K8s** | `helm install` | 프로덕션 등급, HPA, PDB, CronJob, PrometheusRule 포함 |
| **파서 확장** | [Docker Compose 가이드](./docs/deployment/docker_compose.md) | 필요한 CPU / GPU 프로필 시작 |

프로덕션 설정과 업그레이드 순서는 [Docker Compose 가이드](./docs/deployment/docker_compose.md), [Helm 배포 가이드](./docs/deployment/helm.md), [운영 핸드북](./docs/deployment/runbook.md)을 참조하세요.

---

## 기능 가이드

| 가이드 | 설명 |
|:---|:---|
| [청크 미리보기](./docs/guides/chunk_preview.md) | 문서 분할 시각화와 파라미터 조정 |
| [지식 그래프](./docs/guides/knowledge_graph.md) | KG 추출, 시각화, RAG 강화 |
| [문서 ACL](./docs/guides/document_acl.md) | 문서 단위 접근 제어와 Security Trimming |
| [URL 가져오기](./docs/guides/url_ingest.md) | 원격 URL 수집과 일괄 가져오기 |
| [문서 버전](./docs/guides/document_versions.md) | 파이프라인 버전 관리와 롤백 |
| [스파스 검색](./docs/guides/sparse_retrieval.md) | SPLADE 스파스 검색 채널 |
| [ColBERT 리랭크](./docs/guides/reranking_colbert.md) | ColBERT 레이트 인터랙션 리랭크 |
| [RAG 최적화](./docs/guides/rag_optimization.md) | 검색과 답변 품질 최적화 |
| [검색 트러블슈팅](./docs/guides/retrieval_debugging.md) | 검색 문제 진단 |
| [SAML SSO](./docs/guides/saml_sso.md) | SAML 싱글 사인온 연동 |
| [공개 벤치마크](./docs/guides/public_benchmarks_zh.md) | 재현 가능한 중국어 벤치마크(MIRACL-zh / CFEVER) |
| [빠른 시작](./docs/quickstart.md) | 소스에서 개발 |
| [운영 핸드북](./docs/deployment/runbook.md) | 프로덕션 운영과 트러블슈팅 |

---

## 개발

push 전에 CI와 동일한 체크를 실행하세요(백엔드 + 프런트엔드).

```bash
# 전체 체크(백엔드 lint/test + 프런트엔드 lint/test)
make enterprise-checks

# 백엔드만
make verify && make test

# 프런트엔드만
cd web && pnpm lint && pnpm test
```

---

## 로드맵

제공된 기능은 위의 비교표를 참조하세요. 단기 계획:

- [ ] RAG 전용 디버깅 편성(범용 에이전트 캔버스가 아님)
- [ ] 더 많은 데이터 소스 커넥터(Confluence / S3 / Notion)
- [ ] 언어 간 검색
- [ ] 통합 LLM-as-Judge(G-Eval + Self-Consistency)

> 로드맵, 기능 요청, 투표는 [GitHub Issues](https://github.com/skygazer42/MimirQ/issues)에서 관리합니다.

---

## 기여하기

코드 기여, 문제 보고, 기능 제안 전에 [CONTRIBUTING.md](./.github/CONTRIBUTING.md)를 참조하세요. 로컬 개발 절차는 [빠른 시작](./docs/quickstart.md)에 있으며, push 전에 `make enterprise-checks`를 실행해야 합니다.

```bash
# 포크 후 클론
git clone https://github.com/<your-username>/MimirQ.git
cd MimirQ
make init

# 로컬 개발
make infra-up           # 인프라 기동
make models             # 고정 버전의 DeepDoc 모델 다운로드 및 검증
cd web && pnpm dev      # 프런트엔드 개발
python main.py          # 백엔드 개발

# push 전 체크
make enterprise-checks
```

---

## 라이선스

이 프로젝트는 [Apache License 2.0](LICENSE)에 따라 라이선스됩니다. 서드파티 컴포넌트(RAGFlow/DeepDoc에서 vendored한 코드와 빌드 시 다운로드되는 모델 가중치 포함)의 귀속 표시는 [NOTICE](NOTICE)에 기록되어 있습니다.

> **PyMuPDF (AGPL-3.0) 주의**: 기본 PDF 파싱은 PyMuPDF를 사용할 수 있으며, 그 라이선스는 AGPL-3.0 / 상용 듀얼 라이선스입니다. 이 소프트웨어를 SaaS 형태로 네트워크 서비스로 제공하는 경우, AGPL의 네트워크 조항에 따라 결합 저작물 전체의 소스 공개가 요구될 수 있습니다. 이 제약을 피하려면 관대한 라이선스의 파싱 백엔드(pypdf / pdfplumber)로 전환하세요. 자세한 내용은 NOTICE를 참조하세요.

---

## 감사의 말

MimirQ는 뛰어난 오픈소스 생태계 위에 구축되었습니다. 다음 프로젝트에 감사드립니다.

[Dify](https://github.com/langgenius/dify) · [RAGFlow](https://github.com/infiniflow/ragflow) · [FastAPI](https://fastapi.tiangolo.com/) · [LangChain](https://langchain.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [Milvus](https://milvus.io/) · [Next.js](https://nextjs.org/) · [PostgreSQL](https://www.postgresql.org/) · [RAGAS](https://docs.ragas.io/) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [MinerU](https://github.com/opendatalab/MinerU) · [Tailwind CSS](https://tailwindcss.com/) · [shadcn/ui](https://ui.shadcn.com/)

---

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=skygazer42/MimirQ&type=Date)](https://star-history.com/#skygazer42/MimirQ&Date)

</div>
