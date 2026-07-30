import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'MimirQ Docs',
  tagline: '可控、可观测、可回归的企业知识能力层',
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
      title: 'MimirQ',
      logo: {
        alt: 'MimirQ',
        src: 'img/logo.svg',
      },
      items: [
        {
          to: '/docs/ops/getting-started',
          position: 'left',
          label: '快速开始',
          activeBaseRegex: '^/docs/ops/getting-started',
        },
        {
          type: 'docSidebar',
          sidebarId: 'guide',
          position: 'left',
          label: '使用指南',
        },
        {
          type: 'dropdown',
          position: 'left',
          label: '开发者资源',
          items: [
            {to: '/docs/backend/welcome', label: '后端契约'},
            {to: '/docs/frontend/welcome', label: '前端路由'},
            {to: '/docs/integration/welcome', label: '集成与联调'},
          ],
        },
        {
          to: '/docs/ops/welcome',
          position: 'left',
          label: '运维',
          activeBaseRegex: '^/docs/ops/(?!getting-started)',
        },
        {
          type: 'localeDropdown',
          position: 'right',
        },
        {
          href: 'https://skygazer42.github.io/MimirQ/',
          label: 'API',
          position: 'right',
        },
        {
          href: 'https://github.com/skygazer42/MimirQ',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    colorMode: {
      defaultMode: 'light',
      disableSwitch: false,
      respectPrefersColorScheme: false,
    },
    footer: {
      style: 'light',
      copyright: `© ${new Date().getFullYear()} MimirQ · 可控、可观测、可回归`,
    },
    tableOfContents: {
      minHeadingLevel: 2,
      maxHeadingLevel: 3,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
