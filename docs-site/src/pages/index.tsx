import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';
import HomepageFeatures from '@site/src/components/HomepageFeatures';

import styles from './index.module.css';

/* ────────────────────────────────────────────────────
 * i18n copy
 * ──────────────────────────────────────────────────── */

function copy(locale: string) {
  const en = locale === 'en';
  return {
    heroLead: en
      ? 'Narrative handbook covering backend contracts, frontend routes, integration flows, and ops runbooks. OpenAPI remains the schema SSOT in Redoc.'
      : '叙事型全栈手册：后端契约、前端路由、联调序列与运维 Runbook。OpenAPI 仍以 Redoc 为 Schema 单一事实来源。',
    backend: en ? 'Backend' : '后端（Backend）',
    frontend: en ? 'Frontend' : '前端（Frontend）',
    integration: en ? 'Integration' : '集成（Integration）',
    ops: en ? 'Ops' : '运维（Ops）',
    redoc: en ? 'Full OpenAPI (Redoc)' : '全量 OpenAPI（Redoc）',
    searchHint: en
      ? 'Use the top search bar to find operations (e.g. ingestion, datasets).'
      : '使用顶部搜索查找操作名（如 ingestion、datasets）。',
    rolesTeaser: en ? 'Integration \u2014 by role:' : '集成视角 \u2014 按角色入门：',
    roleAdmin: en ? 'Tenant / admin' : '租户与管理员',
    roleEngineer: en ? 'Integration engineer' : '集成工程师',
    roleSre: en ? 'SRE / ops' : '运维 / SRE',

    coreFeaturesTitle: en ? 'Core Features' : '核心特性一览',
    techStackTitle: en ? 'Tech Stack' : '技术栈',
    pipelineTitle: en ? 'RAG Pipeline' : 'RAG 管线流程',
    pipelineIngest: en ? 'Ingestion Pipeline' : '入库流程',
    pipelineQuery: en ? 'Query Pipeline' : '问答流程',
    useCasesTitle: en ? 'Use Cases' : '适用场景',
    quickLinksTitle: en ? 'Quick Links' : '快速链接',
    quickStart: en ? 'Quick Start' : '快速开始',
    externalLinks: en ? 'External Resources' : '外部资源',

    category: en ? 'Category' : '类别',
    capability: en ? 'Capability' : '能力',
    detail: en ? 'Detail' : '说明',

    layer: en ? 'Layer' : '层级',
    tech: en ? 'Technology' : '技术',
  };
}

/* ────────────────────────────────────────────────────
 * Data
 * ──────────────────────────────────────────────────── */

const CORE_FEATURES = [
  ['混合检索', 'Vector + BM25 + SPLADE + ColBERT ANN', 'RRF 融合排序，支持 Reranker'],
  ['多引擎解析', 'PyMuPDF / MinerU / Marker', '自动分块、表格/图像抽取'],
  ['知识图谱', '实体/关系抽取 + 社区发现', 'KG 增强 RAG，子图扩展检索'],
  ['RAGAS 评测', 'Faithfulness / Relevancy / Context Recall', '回归门禁，CI 集成'],
  ['文档 ACL', 'Security Trimming + RBAC', '查询时分片级权限过滤'],
  ['多租户', '租户隔离 / SCIM / 审计日志', '企业合规就绪'],
];

const TECH_STACK = [
  ['Backend', 'Python 3.11+ / FastAPI 0.135 / SQLAlchemy 2.0 / Arq'],
  ['Vector DB', 'Milvus (HNSW / IVF-FLAT)'],
  ['Storage', 'PostgreSQL / Redis / MinIO'],
  ['Embedding', 'BAAI/bge-m3 (15 models / 7 providers)'],
  ['Frontend', 'Next.js 15 / React 19 / TypeScript / TailwindCSS'],
  ['Docs', 'Docusaurus 3 / Redoc (OpenAPI)'],
];

const USE_CASES = [
  { icon: '\u{1F4DA}', title: '企业知识库', desc: '内部文档、Wiki、流程规范统一检索' },
  { icon: '\u{1F4BB}', title: '技术文档', desc: 'API 手册、SDK 文档智能问答' },
  { icon: '\u{1F4DC}', title: '合规文档', desc: '法规、标准、审计报告语义检索 + ACL' },
  { icon: '\u{1F4DE}', title: '客服知识', desc: '常见问题、工单、SOP 实时召回辅助' },
];

const INGEST_PIPELINE = `Upload -> File Router -> PDF / Docx / HTML Parser
  -> Chunker (Recursive / Semantic) -> Embedding (bge-m3)
  -> Vector Store (Milvus) + BM25 Index
  -> KG Extractor (optional) -> Entity & Relation Store`;

const QUERY_PIPELINE = `User Query -> Query Rewriter (HyDE / Multi-Query)
  -> Hybrid Retriever (Vector + BM25 + SPLADE + ColBERT)
  -> RRF Fusion -> Reranker (Cross-Encoder)
  -> KG Subgraph Expansion (optional)
  -> Context Assembly -> LLM Generation (Streaming)
  -> RAGAS Auto-Eval (async)`;

/* ────────────────────────────────────────────────────
 * HeroBanner
 * ──────────────────────────────────────────────────── */

function HeroBanner() {
  const {siteConfig, i18n} = useDocusaurusContext();
  const t = copy(i18n.currentLocale);
  return (
    <header className={clsx('hero', styles.heroBanner)}>
      <div className="container">
        <Heading as="h1" className="hero__title">
          {siteConfig.title}
        </Heading>
        <p className="hero__subtitle">{siteConfig.tagline}</p>
        <p className={styles.heroLead}>{t.heroLead}</p>

        <div className={styles.buttons}>
          <Link className="button button--secondary button--lg" to="/docs/ops/getting-started">
            {t.quickStart}
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/backend/welcome">
            {t.backend}
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/frontend/welcome">
            {t.frontend}
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/integration/welcome">
            {t.integration}
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/ops/welcome">
            {t.ops}
          </Link>
        </div>

        <div className="margin-top--md">
          <a
            className={clsx('button button--link button--lg', styles.redocLink)}
            href="https://skygazer42.github.io/MimirQ/">
            {t.redoc}
          </a>
        </div>

        <p className={clsx('margin-top--md margin-bottom--none text--center', styles.rolesTeaser)}>
          <span>{t.rolesTeaser}</span>{' '}
          <Link to="/docs/integration/roles/admin">{t.roleAdmin}</Link>
          {' \u00B7 '}
          <Link to="/docs/integration/roles/integration-engineer">{t.roleEngineer}</Link>
          {' \u00B7 '}
          <Link to="/docs/integration/roles/sre-ops">{t.roleSre}</Link>
        </p>
      </div>
    </header>
  );
}

/* ────────────────────────────────────────────────────
 * CoreFeaturesTable
 * ──────────────────────────────────────────────────── */

function CoreFeaturesTable() {
  const {i18n} = useDocusaurusContext();
  const t = copy(i18n.currentLocale);
  return (
    <section className={styles.section}>
      <div className="container">
        <Heading as="h2" className="text--center margin-bottom--lg">
          {t.coreFeaturesTitle}
        </Heading>
        <table className={styles.featureTable}>
          <thead>
            <tr>
              <th>{t.category}</th>
              <th>{t.capability}</th>
              <th>{t.detail}</th>
            </tr>
          </thead>
          <tbody>
            {CORE_FEATURES.map(([cat, cap, detail], idx) => (
              <tr key={idx}>
                <td><strong>{cat}</strong></td>
                <td>{cap}</td>
                <td>{detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* ────────────────────────────────────────────────────
 * TechStack
 * ──────────────────────────────────────────────────── */

function TechStack() {
  const {i18n} = useDocusaurusContext();
  const t = copy(i18n.currentLocale);
  return (
    <section className={styles.sectionAlt}>
      <div className="container">
        <Heading as="h2" className="text--center margin-bottom--lg">
          {t.techStackTitle}
        </Heading>
        <table className={styles.featureTable}>
          <thead>
            <tr>
              <th>{t.layer}</th>
              <th>{t.tech}</th>
            </tr>
          </thead>
          <tbody>
            {TECH_STACK.map(([layer, tech], idx) => (
              <tr key={idx}>
                <td><strong>{layer}</strong></td>
                <td>{tech}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* ────────────────────────────────────────────────────
 * RagPipelineSection
 * ──────────────────────────────────────────────────── */

function RagPipelineSection() {
  const {i18n} = useDocusaurusContext();
  const t = copy(i18n.currentLocale);
  return (
    <section className={styles.section}>
      <div className="container">
        <Heading as="h2" className="text--center margin-bottom--lg">
          {t.pipelineTitle}
        </Heading>

        <div className={styles.pipelineBox}>
          <Heading as="h4">{t.pipelineIngest}</Heading>
          <pre>{INGEST_PIPELINE}</pre>
        </div>

        <div className={styles.pipelineBox}>
          <Heading as="h4">{t.pipelineQuery}</Heading>
          <pre>{QUERY_PIPELINE}</pre>
        </div>
      </div>
    </section>
  );
}

/* ────────────────────────────────────────────────────
 * UseCases
 * ──────────────────────────────────────────────────── */

function UseCases() {
  const {i18n} = useDocusaurusContext();
  const t = copy(i18n.currentLocale);
  return (
    <section className={styles.sectionAlt}>
      <div className="container">
        <Heading as="h2" className="text--center margin-bottom--lg">
          {t.useCasesTitle}
        </Heading>
        <div className={styles.useCaseGrid}>
          {USE_CASES.map((uc, idx) => (
            <div key={idx} className={styles.useCaseCard}>
              <div style={{fontSize: '2rem', marginBottom: '0.5rem'}}>{uc.icon}</div>
              <Heading as="h4">{uc.title}</Heading>
              <p>{uc.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ────────────────────────────────────────────────────
 * QuickLinks
 * ──────────────────────────────────────────────────── */

function QuickLinks() {
  const {i18n} = useDocusaurusContext();
  const t = copy(i18n.currentLocale);
  return (
    <section className={styles.section}>
      <div className="container text--center">
        <Heading as="h2" className="margin-bottom--md">
          {t.quickLinksTitle}
        </Heading>
        <p className="text--italic margin-bottom--lg">{t.searchHint}</p>
        <div className={styles.quickLinks}>
          <Link
            className="button button--outline button--primary button--md"
            to="/docs/ops/getting-started">
            {t.quickStart}
          </Link>
          <a
            className="button button--outline button--primary button--md"
            href="https://skygazer42.github.io/MimirQ/">
            OpenAPI / Redoc
          </a>
          <a
            className="button button--outline button--primary button--md"
            href="https://github.com/skygazer42/MimirQ">
            GitHub
          </a>
          <Link
            className="button button--outline button--primary button--md"
            to="/docs/backend/welcome">
            Backend Docs
          </Link>
          <Link
            className="button button--outline button--primary button--md"
            to="/docs/integration/welcome">
            Integration Guide
          </Link>
        </div>
      </div>
    </section>
  );
}

/* ────────────────────────────────────────────────────
 * Page
 * ──────────────────────────────────────────────────── */

export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout title={siteConfig.title} description={siteConfig.tagline}>
      <HeroBanner />
      <main>
        <HomepageFeatures />
        <CoreFeaturesTable />
        <TechStack />
        <RagPipelineSection />
        <UseCases />
        <QuickLinks />
      </main>
    </Layout>
  );
}
