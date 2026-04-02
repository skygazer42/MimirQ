import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

import styles from './index.module.css';

function copy(locale: string) {
  const en = locale === 'en';
  return {
    heroLead: en
      ? 'Narrative handbook: backend contracts, frontend routes, integration flows, and ops runbooks. OpenAPI remains the schema SSOT in Redoc.'
      : '叙事型全栈手册：后端契约、前端路由、联调序列与运维 Runbook。OpenAPI 仍以 Redoc 为 Schema 单一事实来源。',
    backend: en ? 'Backend' : '后端（Backend）',
    frontend: en ? 'Frontend' : '前端（Frontend）',
    integration: en ? 'Integration' : '集成（Integration）',
    ops: en ? 'Ops' : '运维（Ops）',
    redoc: en ? 'Full OpenAPI (Redoc)' : '全量 OpenAPI（Redoc）',
    searchHint: en
      ? 'Use the top search bar to find operations (e.g. ingestion, datasets).'
      : '使用顶部搜索查找操作名（如 ingestion、datasets）。',
    rolesTeaser: en ? 'Integration — by role:' : '集成视角 — 按角色入门：',
    roleAdmin: en ? 'Tenant / admin' : '租户与管理员',
    roleEngineer: en ? 'Integration engineer' : '集成工程师',
    roleSre: en ? 'SRE / ops' : '运维 / SRE',
  };
}

function HomepageHeader() {
  const {siteConfig, i18n} = useDocusaurusContext();
  const t = copy(i18n.currentLocale);
  return (
    <header className={clsx('hero hero--primary', styles.heroBanner)}>
      <div className="container">
        <Heading as="h1" className="hero__title">
          {siteConfig.title}
        </Heading>
        <p className="hero__subtitle">{siteConfig.tagline}</p>
        <p className="margin-bottom--md">{t.heroLead}</p>
        <div className={styles.buttons}>
          <Link
            className="button button--secondary button--lg margin-right--md"
            to="/docs/backend/welcome">
            {t.backend}
          </Link>
          <Link
            className="button button--secondary button--lg margin-right--md"
            to="/docs/frontend/welcome">
            {t.frontend}
          </Link>
          <Link
            className="button button--secondary button--lg margin-right--md"
            to="/docs/integration/welcome">
            {t.integration}
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/ops/welcome">
            {t.ops}
          </Link>
        </div>
        <div className="margin-top--md">
          <a
            className="button button--link button--lg"
            href="https://skygazer42.github.io/MimirQ/">
            {t.redoc}
          </a>
        </div>
        <p className="margin-top--md margin-bottom--none text--center">
          <span className="text--secondary">{t.rolesTeaser}</span>{' '}
          <Link to="/docs/integration/roles/admin">{t.roleAdmin}</Link>
          {' · '}
          <Link to="/docs/integration/roles/integration-engineer">{t.roleEngineer}</Link>
          {' · '}
          <Link to="/docs/integration/roles/sre-ops">{t.roleSre}</Link>
        </p>
      </div>
    </header>
  );
}

export default function Home(): ReactNode {
  const {siteConfig, i18n} = useDocusaurusContext();
  const t = copy(i18n.currentLocale);
  return (
    <Layout title={siteConfig.title} description={siteConfig.tagline}>
      <HomepageHeader />
      <main className="container margin-vert--lg">
        <p className="text--center text--italic">{t.searchHint}</p>
      </main>
    </Layout>
  );
}
