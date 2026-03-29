# Globalization, Security & Accessibility Plan (2026-03-24)

## 1. 国际化与全球化 (i18n & Globalization)

### 1.1 零技术债 i18n 迁移
- [ ] **引入 `next-intl`**: 在 `web/app/[locale]` 层面实现路由国际化，将文案从业务组件中彻底抽离。
- [ ] **RTL (从右向左) 支持**: 虽然目前主打中文，但在设计系统级别支持 `dir="rtl"` 属性，为阿拉伯语等市场做前瞻性布局。

### 1.2 内容语义感知

## 2. 内容安全与 XSS 防护 (Security & Sanitization)

### 2.1 Markdown 渲染清洗
- [ ] **图片代理加密**: RAG 检索到的外部链接图片，应通过后端或代理服务进行处理，防止泄露用户 IP 地址给第三方攻击者。

### 2.2 响应头加固
- [ ] **严格 CSP 配置**: 在 `next.config.mjs` 中启用 CSP，禁止 `unsafe-inline` 脚本。

## 3. 包容性设计 (Accessibility/a11y)

### 3.1 3D 图谱无障碍化
- [ ] **键盘漫游**: 实现 3D 空间内的 `Tab` 键节点跳转逻辑。

### 3.2 语义化 HTML
- [ ] **Aria-Label 补全**: 遍历全站图标按钮 (Icon Buttons)，补全 `aria-label`，确保无文案按钮在屏幕阅读器下也是“可理解”的。

## 4. Next.js 16 架构优化

### 4.1 RSC 数据预取
- [ ] **Server Actions 深度应用**: 将目前的 `api-client` 部分读操作迁移至 Server Components。
- [ ] **动态导入 (Suspense Boundary)**: 为 `MonacoEditor` 和 `Plotly` 增加更精细的 `Suspense` 边界，并在数据加载时显示品牌一致的加载态动画。
