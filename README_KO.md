<div align="center">

<img src="./images/logo.png" alt="MimirQ: 검사·회귀·거버넌스가 가능한 오픈소스 RAG 지식베이스" width="100%"/>

<p><b>풀스택 오픈소스, 중국어 우선 엔터프라이즈 RAG 지식베이스</b><br/>파싱, 청킹, 검색, 생성, 인용을 대상으로 파이프라인 전체의 검사·디버깅·회귀 검증을 제공합니다.</p>

<p>
  <a href="#제품-화면"><b>제품 화면</b></a> ·
  <a href="#빠른-시작"><b>빠른 시작</b></a> ·
  <a href="#dify-연동"><b>Dify 연동</b></a> ·
  <a href="#운영-환경-검증"><b>800문항 벤치마크</b></a> ·
  <a href="https://skygazer42.github.io/MimirQ/"><b>API 문서</b></a>
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

## 프로젝트 개요

**MimirQ**(지혜의 샘을 지키는 북유럽 신화의 수호자 **Mímir**에서 유래)는 **전체 체인 관측 가능성**에 집중한 RAG 지식베이스 Q&A 플랫폼입니다. 프런트엔드와 백엔드 모두 오픈소스이며, Docker Compose 또는 Helm으로 배포할 수 있습니다.

<table>
  <tr>
    <td align="center" width="25%"><strong>30</strong><br/><sub>파싱 백엔드</sub></td>
    <td align="center" width="25%"><strong>86</strong><br/><sub>청킹 전략</sub></td>
    <td align="center" width="25%"><strong>13</strong><br/><sub>리랭커</sub></td>
    <td align="center" width="25%"><strong>800</strong><br/><sub>고정 문항 세트 평가</sub></td>
  </tr>
</table>

<table>
  <tr>
    <td width="50%"><strong>관측 가능</strong><br/><sub>파싱 결과, 청크 경계, 검색과 리랭크 과정</sub></td>
    <td width="50%"><strong>추적 가능</strong><br/><sub>문장 단위 인용, 버전, 근거, 전체 트레이스</sub></td>
  </tr>
  <tr>
    <td><strong>거버넌스</strong><br/><sub>문서 ACL, RBAC, 마스킹, 감사, 세이프티 레일</sub></td>
    <td><strong>회귀 검증</strong><br/><sub>골든 세트, 평가 대시보드, 릴리스 게이트</sub></td>
  </tr>
</table>

<details>
<summary><b>프로젝트 배경</b></summary>

MimirQ는 하나의 구체적인 행정 서비스 Q&A 프로젝트에서 시작되었습니다. 시스템은 이미 질문에 답할 수 있었지만, 답이 틀렸을 때 그 원인이 파싱·청킹·검색·리랭크·생성 중 어디에 있는지 명확히 가려낼 수 없었습니다. 행정 지식에는 지역별 버전, 정책 갱신, 스캔 문서와 표가 있으며, 유창하지만 오래된 정책을 인용한 답변은 "모른다"라고 분명히 말하는 것보다 더 위험합니다.

기존 플랫폼은 워크플로나 에이전트에는 강하지만, RAG 문제 해결에 필요한 파싱·인덱스·검색·인용·평가가 서로 다른 컴포넌트에 흩어져 있곤 합니다. MimirQ는 또 하나의 범용 노드 캔버스를 만드는 대신, 검사 가능한 RAG 체인에 집중합니다.

> **MimirQ는 RAG 결과를 설명·추적·검증할 수 있도록 하는 것을 목표로 합니다.**

</details>

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
- 호스트 소스 시작에는 Python 3.11+, Node.js 20+, pnpm 10.26도 필요
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
| **호스트 소스 시작** | 프런트엔드·백엔드 개발, 핫 리로드 | 웹, API는 호스트에서 실행하고, 필요할 때만 워커를 추가로 실행합니다. 의존 서비스는 Docker에서 실행 |

### 방법 1: Docker로 일괄 시작

```bash
make up-web
make api-ping
```

[http://localhost:3000](http://localhost:3000)에 접속합니다. 초기 관리자를 설정하지 않았다면 화면에서 첫 계정을 등록하세요. 첫 빌드, 프록시, 운영 시크릿, 네트워크 설정은 [Docker Compose 가이드](./docs/deployment/docker_compose.md)를 참조하세요.

### 방법 2: 프런트엔드와 백엔드를 호스트에서 시작

호스트 의존성을 설치하고 인프라 서비스를 시작합니다.

```bash
make setup-host
```

`make setup-host`는 호스트 의존성을 설치하고 Docker 인프라를 시작합니다. 기본 구성에서는 터미널 두 개를 사용합니다.

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

MimirQ는 7개 구역 단위와 1개 시 단위 지식베이스에 걸친 **시 단위 행정 Q&A 어시스턴트**에 사용되고 있습니다. 최신 직접 검색 재측정은 입력 SHA-256 `5a4c67...fac2`를 사용했으며, 결과는 다음과 같습니다.

| 최신 결과(2026-07-24) | 결과 |
|:---|---:|
| 실행 성공 | **800 / 800**, 타임아웃 0 |
| 정확 / 부분 정확 / 근거 부족 | **797 / 3 / 0** |
| 정확률 / 사용 가능률 | **99.6% / 100%** |
| 평균 / P50 / P95 / P99 | **1.15s / 0.83s / 4.00s / 8.95s** |

이번 직접 검색은 근거 조항 커버리지 99.7%를 달성했습니다. 서로 다른 embedding 런타임에 걸친 다중 지식베이스 검색은 범용 검색 레이어가 샤딩하여 처리하며, 도메인 하드코딩은 없습니다.

독립적인 E2E 부하 테스트에서는, 리랭커를 켜고 요청마다 응답 캐시를 우회한 상태에서 검색 동시성 3으로 12개 요청의 총 소요를 41.46s에서 30.14s로, 대화 동시성 3으로 6개 요청을 54.61s에서 31.60s로 줄였으며, 두 경우 모두 오류 0이었습니다. 동시성은 단일 요청 지연을 높입니다. 여기서 검증한 것은 같은 배치의 처리량 개선이며, 하드웨어 용량 상한이 아닙니다.

<details>
<summary><b>2026-07-24 4방향 동일 문항 재측정 펼치기</b></summary>

동일한 고정 800문항을 네 가지 실제 연동 경로로 재측정했습니다.

<!-- 데이터 출처: artifacts/changzhou_dify_4way_800_20260724/comparison_report.json(2026-07-24T04:02:01Z); 입력 SHA-256 5a4c67c42e8f8123774279d46af39ccc793da1b89fdea19a7359f63c8cb2fac2. -->

| 경로 | 실행 성공 | 정확률 / 사용 가능률 | 답변 조항 커버리지 | 답변의 근거 뒷받침 | 오근거율 | 평균 / P50 / P95 |
|:---|---:|---:|---:|---:|---:|---:|
| **MimirQ 직접 검색** | **800 / 800** | **99.6% / 100%** | **99.7%** | **99.8%** | 3.0% | **1.15s / 0.83s / 4.00s** |
| **Dify External → MimirQ** | **800 / 800** | 60.8% / 91.4% | 82.9% | **97.3%** | **2.7%** | 6.69s / 6.09s / 11.79s |
| **Dify HTTP → MimirQ** | **800 / 800** | **67.6% / 93.0%** | **85.6%** | 94.6% | 3.6% | 5.20s / 5.04s / 7.19s |
| **Dify 네이티브 지식** | **800 / 800** | 38.8% / 74.9% | 66.0% | 85.6% | 79.1% | 10.34s / 8.28s / 26.49s |

MimirQ의 두 Dify 경로의 검색 근거 커버리지는 99.7% / 96.8%였지만, 생성된 답변의 조항 커버리지는 82.9% / 85.6%였습니다. 주요 손실은 지식 리콜이 아니라 워크플로 답변 생성에서 발생합니다. 이번에는 네 경로 모두 동시성 3으로 800문항을 완전히 실행했습니다. Dify 네이티브 지식은 MimirQ를 거치지 않으며, 첫 실행의 상류 Nginx 504 2건은 자동 재시도로 복구되어 최종 800 / 800에 성공했습니다.

</details>

[전체 방법론, 지표 정의, 과거 재측정](./docs/benchmarks/changzhou_dify.md) · [Dify 연동 방식과 실제 워크플로](#dify-연동)

---

## API 레퍼런스(OpenAPI / GitHub Pages)

| 리소스 | 링크 / 설명 |
|:---|:---|
| **온라인 API 브라우저(GitHub Pages)** | [https://skygazer42.github.io/MimirQ/](https://skygazer42.github.io/MimirQ/)(Redoc + 전체 `openapi.json`; fork 후에는 `https://<owner>.github.io/<repo>/`로 변경) |
| **리포지토리 가이드** | [docs/api/README.md](./docs/api/README.md)(인증, 베이스 경로, 전체 OpenAPI 태그 대응표) |
| **시나리오별 플로** | [docs/api/workflows.md](./docs/api/workflows.md) |
| **로컬 Swagger** | 백엔드 기동 후 [http://localhost:8000/docs](http://localhost:8000/docs) |
| **OpenAPI 내보내기** | `make openapi-export` → `web/openapi.json` |
| **정적 사이트 빌드** | `make api-docs-build` → `docs/api/site/` |

> 인증 규약: 전역 인증 미들웨어가 없습니다. **모든 라우트는 명시적으로 `get_current_account_id`에 의존해야 합니다.** 테넌트 데이터에 접근하는 라우트는 `get_tenant_id`에도 의존해야 합니다. [backend_structure.md](./docs/backend_structure.md)를 참조하세요.

리포지토리에서 **Settings → Pages → GitHub Actions**를 활성화하세요. `main`에 push하면 [`.github/workflows/api-docs.yml`](./.github/workflows/api-docs.yml)이 실행됩니다.

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
| [API 가이드](./docs/api/README.md) | OpenAPI 태그 대응표, Pages 링크, 정적 빌드 |
| [API 워크플로](./docs/api/workflows.md) | 시나리오별 엔드포인트 순서 |
| [API 개요](./docs/API.md) | OpenAPI SSOT 내비게이션, 분할 레퍼런스, 핸드북 링크 |
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

MimirQ의 공개 연동 테스트를 위해 CNY 50의 API 체험 크레딧을 제공해 주신 [SiliconFlow](https://siliconflow.cn/)에 감사드립니다.

---

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=skygazer42/MimirQ&type=Date)](https://star-history.com/#skygazer42/MimirQ&Date)

</div>
