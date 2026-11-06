# Ragvia 品牌资产

当前产品使用已确认的 Ragvia 品牌：三条路径汇向一点的「归点」符号，以及小写 `ragvia` 轮廓字标。延续雾白、墨色与锈色方向，浅色与深色背景分别使用正式的普通版和反白版。

正式资产统一维护在 [web/public/brand/ragvia/](../../../web/public/brand/ragvia/README.md)：

| 资产 | 用途 |
| --- | --- |
| `logo.svg`、`logo-inverse.svg` | README、登录入口与需要完整品牌识别的区域 |
| `mark.svg`、`mark-inverse.svg` | 导航、小尺寸品牌标记 |
| `favicon.svg` | 浏览器标签页 |
| `app-icon.png`、`icon-192.png`、`icon-512.png`、`app-icon-maskable.svg` | 应用图标与 PWA |

应用通过 [brand.ts](../../../web/lib/brand.ts) 和 [BrandLogo](../../../web/components/brand-logo.tsx) 复用资产，文档站直接读取同一目录。保持原始比例、路径和留白，完整字标使用既有 SVG，不用字体重新拼写或新增图形。

旧 MimirQ 图形和设计探索保留为历史素材，不作为当前产品的品牌规范。历史截图中的旧标识不代表当前界面。
