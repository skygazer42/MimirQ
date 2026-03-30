# Globalization, Security & Accessibility Plan (2026-03-24)

## 1. 国际化与全球化 (i18n & Globalization)

### 1.1 零技术债 i18n 迁移
- [ ] **引入 `next-intl`**: 在 `web/app/[locale]` 层面实现路由国际化，将文案从业务组件中彻底抽离。
- [x] **RTL (从右向左) 支持**: 虽然目前主打中文，但在设计系统级别支持 `dir="rtl"` 属性，为阿拉伯语等市场做前瞻性布局。

### 1.2 内容语义感知

## 2. 内容安全与 XSS 防护 (Security & Sanitization)

### 2.1 Markdown 渲染清洗
- [x] **图片代理加密**: Markdown / RAG 外链图片现在先走同源 `POST` mint opaque token，再由 `/api/markdown-image?token=...` 代理拉取；浏览器不再暴露明文第三方图片 URL，且未配置 `MARKDOWN_IMAGE_PROXY_SECRET` 时保留 legacy query proxy 作为兼容回退。

## 3. 包容性设计 (Accessibility/a11y)

### 3.1 3D 图谱无障碍化
- [x] **键盘漫游**: 实现 3D 空间内的 `Tab` 键节点跳转逻辑。

### 3.2 语义化 HTML
- [x] **Aria-Label 补全**: 遍历全站图标按钮 (Icon Buttons)，补全 `aria-label`，确保无文案按钮在屏幕阅读器下也是“可理解”的。

## 4. Next.js 16 架构优化

### 4.1 RSC 数据预取
- [x] **Server Actions 深度应用**: 将目前的 `api-client` 部分读操作迁移至 Server Components。
