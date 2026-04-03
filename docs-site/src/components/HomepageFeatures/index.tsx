import type {ReactNode} from 'react';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  icon: string;
  title: string;
  description: ReactNode;
};

const FeatureList: FeatureItem[] = [
  {
    icon: '\u{1F50D}',
    title: '混合检索',
    description: (
      <>Vector + BM25 + SPLADE + ColBERT ANN 四路召回，RRF 融合排序，开箱即用。</>
    ),
  },
  {
    icon: '\u{1F4C4}',
    title: '可视化切片',
    description: (
      <>PyMuPDF / MinerU / Marker 等多引擎 PDF 解析，自动分块与元数据提取。</>
    ),
  },
  {
    icon: '\u{1F578}\u{FE0F}',
    title: '知识图谱',
    description: (
      <>实体与关系自动抽取，KG 增强 RAG 检索，社区发现与子图扩展。</>
    ),
  },
  {
    icon: '\u{1F4CA}',
    title: 'RAGAS 评测',
    description: (
      <>Faithfulness / Relevancy / Context Recall 自动评测，回归门禁集成 CI。</>
    ),
  },
  {
    icon: '\u{1F512}',
    title: '文档 ACL',
    description: (
      <>Security Trimming + RBAC 文档级权限控制，查询时过滤不可见分片。</>
    ),
  },
  {
    icon: '\u{1F3E2}',
    title: '企业架构',
    description: (
      <>多租户隔离 / SCIM 用户同步 / 审计日志，满足企业合规要求。</>
    ),
  },
];

function Feature({icon, title, description}: FeatureItem) {
  return (
    <div className={styles.card}>
      <div className={styles.icon}>{icon}</div>
      <Heading as="h3">{title}</Heading>
      <p>{description}</p>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <Heading as="h2" className="text--center margin-bottom--lg">
          核心特性
        </Heading>
        <div className={styles.grid}>
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
