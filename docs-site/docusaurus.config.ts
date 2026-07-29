import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'MimirQ 全栈手册',
  tagline: '使用 · 后端 · 前端 · 集成 · 运维',
  favicon: 'img/favicon.ico',

  url: 'https://skygazer42.github.io',
  baseUrl: '/MimirQ/handbook/',

  organizationName: 'skygazer42',
  projectName: 'MimirQ',

  trailingSlash: false,

  staticDirectories: ['static', '../docs/images'],

  onBrokenLinks: 'throw',

  i18n: {
    defaultLocale: 'zh-Hans',
    locales: ['zh-Hans', 'en'],
    localeConfigs: {
      'zh-Hans': {
        label: '简体中文',
        htmlLang: 'zh-Hans',
        direction: 'ltr',
      },
      en: {
        label: 'English',
        htmlLang: 'en',
        direction: 'ltr',
      },
    },
  },

  themes: ['@docusaurus/theme-mermaid'],

  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  presets: [
    [
      'classic',
      {
        docs: {
          path: 'docs',
          routeBasePath: 'docs',
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/skygazer42/MimirQ/tree/main/docs-site/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/docusaurus-social-card.jpg',
    navbar: {
      title: 'MimirQ 手册',
      logo: {
        alt: 'MimirQ',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'guide',
          position: 'left',
          label: 'Guide',
        },
        {
          type: 'docSidebar',
          sidebarId: 'backend',
          position: 'left',
          label: 'Backend',
        },
        {
          type: 'docSidebar',
          sidebarId: 'frontend',
          position: 'left',
          label: 'Frontend',
        },
        {
          type: 'docSidebar',
          sidebarId: 'integration',
          position: 'left',
          label: 'Integration',
        },
        {
          type: 'docSidebar',
          sidebarId: 'ops',
          position: 'left',
          label: 'Ops',
        },
        {
          type: 'localeDropdown',
          position: 'right',
        },
        {
          href: 'https://skygazer42.github.io/MimirQ/',
          label: 'OpenAPI (Redoc)',
          position: 'right',
        },
        {
          href: 'https://github.com/skygazer42/MimirQ',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: '手册分区',
          items: [
            {label: 'Guide', to: '/docs/guide/welcome'},
            {label: 'Backend', to: '/docs/backend/welcome'},
            {label: 'Frontend', to: '/docs/frontend/welcome'},
            {label: 'Integration', to: '/docs/integration/welcome'},
            {label: 'Ops', to: '/docs/ops/welcome'},
          ],
        },
        {
          title: '参考',
          items: [
            {
              label: '仓库 README',
              href: 'https://github.com/skygazer42/MimirQ/blob/main/README.md',
            },
            {
              label: 'OpenAPI / Redoc',
              href: 'https://skygazer42.github.io/MimirQ/',
            },
            {
              label: '集成排障 (仓库内)',
              href: 'https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md',
            },
          ],
        },
      ],
      copyright: `© ${new Date().getFullYear()} MimirQ · Built with Docusaurus`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
