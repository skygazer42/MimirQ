# 原序 · YUANXU

用户于 2026-10-19 选定「原序 / YUANXU」，比较其他方向后，通过截图明确选择回到原版 V1：方折符号、左下赭橙短线与深墨字标。本套资产及生成源文件已恢复为这版。

**品牌句：从原始资料，到可信答案。**

原序是可观察、可替换、可回归的企业知识基础设施。「原」代表原始资料与来源，「序」代表知识治理及可控流程。品牌强调清晰的来源关系和可验证的过程，不承诺生成内容永远正确。

## 标志

标志以「源线归序」为构形依据：上方归档折角、右下定位折角及左下来源基线，共同形成连续的负形路径。三段共用同样的笔画尺度，色彩只强调来源基线；去掉颜色后仍能识别。

- 标准画布：64 × 64。
- 着色区域：横纵均为 8–56，主笔画宽度 12，最小间隙 8。
- 安全距离：从着色边缘向外至少保留 12 个设计单位，相邻文字与其他品牌不能侵入。
- 标准中英组合建议宽度 ≥184px；紧凑组合 ≥112px；独立标志建议 ≥24px。
- 小于 24px 的标签页场景使用专门的 favicon，包含像素对齐的光学校正。
- 保持原比例、负形和线段关系，不添加渐变、阴影、旋转或描边。

SVG 均为可编辑路径。中文轮廓基于 Noto Sans SC 的 650 字重；YUANXU 字标为本套资产单独绘制的几何字形，不依赖字体安装。

## 色彩

| 名称 | 色值 | 用途 |
| --- | --- | --- |
| 雾白 | `#F6F7F8` | 品牌浅底、反白标志主体 |
| 深墨 | `#20262E` | 标志主体、正文与深底 |
| 赭橙 | `#B84A2A` | 来源基线、品牌识别、重点定位 |
| 浅赭橙 | `#F09A77` | 深底上的品牌强调 |
| 选中底 | `#F9ECE6` | 浅色品牌选中背景 |
| 分隔线 | `#DDE1E4` | 结构分隔 |
| 次级文字 | `#606A75` | 浅底上的辅助文字 |

大部分面积使用雾白和深墨，赭橙控制在约 10% 以内。深底使用 `logo-inverse.svg`，不直接把浅底的深赭橙套到深色背景。

品牌色与成功、警告、失败等状态分别定义。重要状态同时提供文字和图标；产品接入时从既有语义变量映射，避免机械替换全部颜色。

## 字体与图标

- 中文界面：Noto Sans SC / 思源黑体；标志的中文字形已转轮廓。
- 英文字标：定制 YUANXU 几何字形，仅用于字标，不当作正文字体。
- 正文按现有产品字体与语义字号实现，避免为品牌更换破坏工作台密度。
- 功能图标：24px 画布、1.75px 描边、方形端点与直角连接。提供知识库、数据治理、检索、引用、回归评测、链路追踪六枚。
- 图标 SVG 使用 `currentColor`；通过内联或 SVG sprite 继承颜色。作为 `<img>` 引用时，使用自身的默认单色。
- `fonts/noto-sans-sc-brand.woff2` 是品牌预览页的有限字符子集，不作为整个产品的中文字体。

SVG sprite 使用示例：

```html
<svg width="24" height="24" aria-label="检索" role="img">
  <use href="/brand/yuanxu/icons/sprite.svg#yuanxu-retrieval"></use>
</svg>
```

## 文件与用途

所有可用资产位于 `web/public/brand/yuanxu/`，详细尺寸索引见 `assets.json`。

| 文件 | 用途 |
| --- | --- |
| `logo.svg` / `logo-inverse.svg` | 标准中英组合、深底组合 |
| `logo-ink.svg` / `logo-white.svg` / `logo-rust.svg` | 单色印刷、刻印、反白 |
| `logo-compact.svg` / `logo-compact-inverse.svg` | 顶栏、窄幅品牌入口 |
| `logo-en.svg` / `logo-stacked.svg` | 英文组合、纵向组合 |
| `wordmark-zh.svg` / `wordmark-en.svg` | 独立中英文字标 |
| `mark*.svg` | 独立符号，多色及单色 |
| `app-icon*.svg` | 方形应用图标底稿，平台自行添加外部遮罩 |
| `icon-192.png` / `icon-512.png` | PWA 的普通图标 |
| `icon-maskable-512.png` | PWA 可遮罩图标，主标志位于中央安全圆内 |
| `apple-touch-icon.png` | 180px Apple 图标 |
| `favicon.svg` | 响应深浅色偏好的透明 SVG 标签页图标 |
| `favicon.ico` | 包含 16、32、48px 的多分辨率兼容图标 |
| `favicon-16.png` / `favicon-32.png` / `favicon-48.png` | 独立像素图标，带深墨底 |
| `logo*@2x.png` / `mark-*.png` | 透明 PNG，可用于不支持 SVG 的场景 |
| `social-card.svg` / `social-card.png` | 1200 × 630 分享封面 |
| `icons/*.svg` / `icons/sprite.svg` | 六枚功能图标及 sprite |
| `tokens.css` / `tokens.json` | 品牌变量与几何规范 |
| `brand-overview.svg` / `brand-overview.png` | 1600 × 1060 品牌总览 |
| `brandbook.html` | 可浏览、可下载的品牌资产页 |
| `yuanxu-brand-kit.zip` | 全套资产、规范与生成源文件 |

本地预览地址：`http://127.0.0.1:3000/brand/yuanxu/brandbook.html`。

## 来源、许可与边界

- 符号、英文字形、图标与排版为本次设计的矢量资产，未使用外部图标库或位图生成素材。
- 中文字形和预览页字体源自 Noto Sans SC，使用 SIL Open Font License 1.1；完整许可随资产放在 `fonts/OFL.txt`。转换为轮廓不改变源字体的许可记录。
- 这轮交付品牌资产和应用预览；认证行为、API、数据库、服务和仓库命名不在本轮变更中。
- 品牌名已由用户选定，商标及域名可用性尚未查询。

## 再生成

源文件位于本目录的 `source/`，工具仅用于设计导出，不新增产品运行依赖。

1. 使用具备 `fonttools`、`brotli` 的 Python，运行 `source/generate.py --font <NotoSansSC-VF.ttf 路径> --font-license <OFL.txt 路径>`。
2. 使用具备 `sharp` 的 Node.js，运行 `source/render.mjs --sharp-module <sharp 模块绝对路径>`。
3. 使用具备 Pillow 的 Python，运行 `source/package.py --assets <资产目录> --guide <本说明路径> --report <检查报告路径>`，验证透明导出、ICO、遮罩安全范围、文字对比度和本地资源引用，并重新打包。
4. 生成工具默认以仓库根目录为输出基准。单独使用压缩包时，给前两条命令加上 `--out .`，字体许可可指定 `fonts/OFL.txt`。压缩包同步包含本说明与 `source/`，不递归加入自身。

实际视觉证据及验收记录位于 `artifacts/rebrand/`。
