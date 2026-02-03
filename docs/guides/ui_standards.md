# UI 规范（Frontend UI Standards）

目标：让 UI 持续保持一致、可维护、可访问（a11y），避免引入“AI 风格”的不稳定视觉和性能开销。

## 1. Token-first（语义化 tokens 优先）

项目已在 Tailwind 中定义语义 token（`bg-background`、`text-foreground`、`border-border`、`bg-card`、`bg-popover` 等）。

- 优先使用语义 token，而不是直接写颜色（如 `bg-white`、`text-cyan-500`）
- 组件风格优先走现有 primitives（Radix + shadcn/ui 风格）

### 自动检查

```bash
cd web
pnpm run ui-check
```

该检查会阻止部分高风险的硬编码类名回归（例如 `bg-white`、`border-white`、`text-cyan-*` 等）。
同时也会阻止在 UI 代码中使用原生浏览器对话框（`confirm()` / `prompt()`），避免阻塞式交互与样式/可访问性不一致。

## 2. Baseline UI（约束）

本项目遵循以下基线规则（节选）：

- **交互**：破坏性/不可逆操作必须使用 `AlertDialog` 二次确认（推荐使用 `web/components/ui/confirm-dialog.tsx` 的 `ConfirmDialog`）
- **交互**：禁止 `window.confirm` / `window.prompt`（改用 `ConfirmDialog` / `Dialog` + `Input/Textarea`）
- **可访问性**：图标按钮必须有 `aria-label`；可聚焦元素必须有可见 focus 样式
- **动画**：默认不加动画；需要动画时只动 `transform/opacity`，交互反馈不超过 200ms，尊重 `prefers-reduced-motion`
- **性能**：避免大面积 `backdrop-filter/blur`（尤其叠加在全屏遮罩上）
- **排版**：标题用 `text-balance`，正文/说明用 `text-pretty`

## 3. 组件优先级

1. 优先复用 `web/components/ui/*` 中已有的 UI primitives
2. 不要在同一个交互面里混用多个 primitive 系统（例如自己手写 focus/keyboard 行为）
3. 新增基础交互组件时，优先使用 Radix primitives（项目已在使用）

## 4. 常见反例（不要做）

- `transition-all`（可能触发布局动画/性能问题）
- 大面积 glow / neon 阴影当作主要强调手段
- 在同一视图里同时使用多套强调色（导致杂乱、难以维护）
- 用 emoji 充当 UI icon（使用一致的 SVG icon set）

## 5. 验证清单（提交前）

```bash
cd web
pnpm run verify
```

推荐同时跑根目录的 CI-like 自检：

```bash
make enterprise-checks
```
