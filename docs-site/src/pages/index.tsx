import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';

import styles from './index.module.css';

type IconName =
  | 'arrow'
  | 'book'
  | 'braces'
  | 'database'
  | 'github'
  | 'network'
  | 'shield'
  | 'terminal';

const ICONS: Record<IconName, ReactNode> = {
  arrow: (
    <>
      <path d="M5 12h14" />
      <path d="m13 6 6 6-6 6" />
    </>
  ),
  book: (
    <>
      <path d="M2 6a2 2 0 0 1 2-2h5a3 3 0 0 1 3 3v13a3 3 0 0 0-3-3H2Z" />
      <path d="M22 6a2 2 0 0 0-2-2h-5a3 3 0 0 0-3 3v13a3 3 0 0 1 3-3h7Z" />
    </>
  ),
  braces: (
    <>
      <path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h1" />
      <path d="M16 21h1a2 2 0 0 0 2-2v-5a2 2 0 0 1 2-2 2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </>
  ),
  github: (
    <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3.3-.4 6.8-1.6 6.8-7A5.4 5.4 0 0 0 19.3 4 5 5 0 0 0 19.2.5S18 0 15 2a13.4 13.4 0 0 0-7 0C5-.1 3.8.5 3.8.5A5 5 0 0 0 3.7 4a5.4 5.4 0 0 0-1.5 3.7c0 5.3 3.5 6.5 6.8 6.9A4.8 4.8 0 0 0 8 18v4" />
  ),
  network: (
    <>
      <rect width="6" height="6" x="9" y="2" rx="2" />
      <rect width="6" height="6" x="16" y="16" rx="2" />
      <rect width="6" height="6" x="2" y="16" rx="2" />
      <path d="M12 8v4m0 0H5v4m7-4h7v4" />
    </>
  ),
  shield: (
    <>
      <path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3Z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  terminal: (
    <>
      <rect width="20" height="16" x="2" y="4" rx="2" />
      <path d="m6 9 3 3-3 3m5 0h4" />
    </>
  ),
};

function Icon({name, size = 20}: {name: IconName; size?: number}) {
  return (
    <svg
      aria-hidden="true"
      className={styles.icon}
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8">
      {ICONS[name]}
    </svg>
  );
}

function getCopy(locale: string) {
  const en = locale === 'en';

  return {
    eyebrow: en ? 'MIMIRQ DOCUMENTATION' : 'MIMIRQ 全栈手册',
    title: en
      ? ['Make knowledge', 'paths explainable.']
      : ['让每一条知识链路，', '都可以被解释。'],
    lead: en
      ? 'Start with a working deployment, then inspect parsing, governance, chunking, retrieval, reranking, citations, and regression gates one layer at a time.'
      : '先跑通一个可用部署，再逐层深入解析、治理、切块、检索、重排、引用与回归门禁。',
    start: en ? 'Start here' : '开始部署',
    fullGuide: en ? 'Read the full guide' : '阅读完整操作指南',
    recommended: en ? 'RECOMMENDED PATH' : '推荐路径',
    duration: en ? 'About 15 minutes' : '约 15 分钟',
    steps: en
      ? ['Create local configuration', 'Connect model services', 'Start API, Web, and infrastructure', 'Create a dataset and verify citations']
      : ['生成本地配置', '连接模型服务', '启动 API、Web 与基础设施', '创建数据集并验证引用'],
    openQuickStart: en ? 'Open quick start' : '打开快速开始',
    pipelineLabel: en ? 'KNOWLEDGE PATH' : '知识链路',
    pipeline: en
      ? ['Assess', 'Parse', 'Govern', 'Chunk', 'Index', 'Retrieve', 'Rerank', 'Cite', 'Evaluate']
      : ['评估', '解析', '治理', '切块', '入库', '召回', '重排', '引用', '评测'],
    chooseTitle: en ? 'Choose the shortest path to your goal' : '选择离目标最近的入口',
    chooseLead: en
      ? 'The handbook is organized by tasks, not by feature inventory.'
      : '手册按真实任务组织，而不是把功能名称堆在一起。',
    paths: en
      ? [
          {icon: 'terminal' as const, label: 'First deployment', title: 'From .env to first login', description: 'Prepare credentials, choose Docker or host processes, and verify readiness.', to: '/docs/ops/getting-started', action: 'Deploy MimirQ'},
          {icon: 'book' as const, label: 'First knowledge base', title: 'From dataset to cited answer', description: 'Upload a document, inspect chunks, test retrieval, and trace the final evidence.', to: '/docs/guide/welcome', action: 'Follow the workflow'},
          {icon: 'braces' as const, label: 'Existing application', title: 'Integrate API, Dify, or a workflow', description: 'Use stable contracts for auth, ingestion, retrieval, streaming, and retries.', to: '/docs/integration/welcome', action: 'Open integration guide'},
        ]
      : [
          {icon: 'terminal' as const, label: '首次部署', title: '从 .env 到首次登录', description: '准备密钥，选择 Docker 或主机进程，完成健康检查。', to: '/docs/ops/getting-started', action: '部署 MimirQ'},
          {icon: 'book' as const, label: '第一个知识库', title: '从数据集到带引用回答', description: '上传文档，检查 Chunk，测试召回，最后回看证据链。', to: '/docs/guide/welcome', action: '跟随完整流程'},
          {icon: 'braces' as const, label: '接入现有业务', title: '集成 API、Dify 或工作流', description: '按稳定契约处理认证、入库、检索、流式输出与重试。', to: '/docs/integration/welcome', action: '查看集成指南'},
        ],
    mapEyebrow: en ? 'SYSTEM MAP' : '手册地图',
    mapTitle: en ? 'Inspect the system by layer' : '按系统层次深入',
    mapLead: en
      ? 'Each area documents its input, output, boundaries, failure modes, and verification path.'
      : '每个分区都说明输入输出、权限边界、失败模式与验证方法。',
    areas: en
      ? [
          {icon: 'database' as const, title: 'Knowledge operations', text: 'Datasets, ingestion, parsing, chunking, retrieval, and evidence.', to: '/docs/guide/welcome'},
          {icon: 'network' as const, title: 'Integration flows', text: 'End-to-end scenarios, tenant headers, SSE, retries, and Dify.', to: '/docs/integration/welcome'},
          {icon: 'shield' as const, title: 'Operations', text: 'Deployment, configuration, health probes, and observability.', to: '/docs/ops/welcome'},
        ]
      : [
          {icon: 'database' as const, title: '知识库运营', text: '数据集、入库、解析、切块、检索与证据。', to: '/docs/guide/welcome'},
          {icon: 'network' as const, title: '集成流程', text: '端到端场景、租户请求头、SSE、重试与 Dify。', to: '/docs/integration/welcome'},
          {icon: 'shield' as const, title: '部署与运维', text: '部署、配置、健康探针、可观测与排障。', to: '/docs/ops/welcome'},
        ],
    closeTitle: en ? 'The code and the handbook evolve together.' : '代码与手册一起演进。',
    closeText: en
      ? 'OpenAPI remains the schema source of truth. The handbook explains how those contracts form a reliable knowledge workflow.'
      : 'OpenAPI 保持 Schema 单一事实来源，手册负责说明这些契约如何组成可靠的知识流程。',
    api: en ? 'Browse API reference' : '查看 API 参考',
    github: 'GitHub',
  };
}

function Hero({copy}: {copy: ReturnType<typeof getCopy>}) {
  return (
    <section className={styles.hero}>
      <div className={styles.heroGrid}>
        <div className={styles.heroCopy}>
          <div className={styles.eyebrow}>
            <span className={styles.signal} />
            {copy.eyebrow}
          </div>
          <h1>
            {copy.title.map((line) => (
              <span key={line}>{line}</span>
            ))}
          </h1>
          <p>{copy.lead}</p>
          <div className={styles.heroActions}>
            <Link className={styles.primaryAction} to="/docs/ops/getting-started">
              {copy.start}
              <Icon name="arrow" size={18} />
            </Link>
            <Link className={styles.secondaryAction} to="/docs/guide/welcome">
              {copy.fullGuide}
            </Link>
          </div>
        </div>

        <aside className={styles.startPanel}>
          <div className={styles.panelHeader}>
            <span>{copy.recommended}</span>
            <small>{copy.duration}</small>
          </div>
          <ol>
            {copy.steps.map((step, index) => (
              <li key={step}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                {step}
              </li>
            ))}
          </ol>
          <Link to="/docs/ops/getting-started">
            {copy.openQuickStart}
            <Icon name="arrow" size={16} />
          </Link>
        </aside>
      </div>

      <div className={styles.pipeline}>
        <span>{copy.pipelineLabel}</span>
        <div>
          {copy.pipeline.map((stage, index) => (
            <span key={stage}>
              {stage}
              {index < copy.pipeline.length - 1 && <i aria-hidden="true" />}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

function StartPaths({copy}: {copy: ReturnType<typeof getCopy>}) {
  return (
    <section className={styles.contentSection}>
      <div className={styles.sectionHeading}>
        <h2>{copy.chooseTitle}</h2>
        <p>{copy.chooseLead}</p>
      </div>
      <div className={styles.pathGrid}>
        {copy.paths.map((path, index) => (
          <Link className={styles.pathCard} key={path.title} to={path.to}>
            <div className={styles.cardMeta}>
              <span>{String(index + 1).padStart(2, '0')}</span>
              <Icon name={path.icon} size={22} />
            </div>
            <small>{path.label}</small>
            <h3>{path.title}</h3>
            <p>{path.description}</p>
            <strong>
              {path.action}
              <Icon name="arrow" size={16} />
            </strong>
          </Link>
        ))}
      </div>
    </section>
  );
}

function SystemMap({copy}: {copy: ReturnType<typeof getCopy>}) {
  return (
    <section className={styles.mapSection}>
      <div className={styles.mapIntro}>
        <span>{copy.mapEyebrow}</span>
        <h2>{copy.mapTitle}</h2>
        <p>{copy.mapLead}</p>
      </div>
      <div className={styles.areaList}>
        {copy.areas.map((area) => (
          <Link key={area.title} to={area.to}>
            <Icon name={area.icon} size={21} />
            <span>
              <strong>{area.title}</strong>
              <small>{area.text}</small>
            </span>
            <Icon name="arrow" size={17} />
          </Link>
        ))}
      </div>
    </section>
  );
}

function Closing({copy}: {copy: ReturnType<typeof getCopy>}) {
  return (
    <section className={styles.closing}>
      <div>
        <h2>{copy.closeTitle}</h2>
        <p>{copy.closeText}</p>
      </div>
      <div className={styles.closingActions}>
        <a href="https://skygazer42.github.io/MimirQ/">
          {copy.api}
          <Icon name="arrow" size={16} />
        </a>
        <a href="https://github.com/skygazer42/MimirQ">
          <Icon name="github" size={18} />
          {copy.github}
        </a>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  const {i18n, siteConfig} = useDocusaurusContext();
  const copy = getCopy(i18n.currentLocale);

  return (
    <Layout title={siteConfig.title} description={siteConfig.tagline}>
      <main className={styles.home}>
        <Hero copy={copy} />
        <StartPaths copy={copy} />
        <SystemMap copy={copy} />
        <Closing copy={copy} />
      </main>
    </Layout>
  );
}
