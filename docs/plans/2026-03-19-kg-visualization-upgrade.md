# 知识图谱可视化升级计划

> 参考 `graph_related/frontend/src/components/GraphPanel.vue` 的交互设计和视觉风格，对 MimirQ 现有的 react-force-graph 图谱可视化做全面升级。基于 2026-03-19 代码审计。

---

## 已有能力

2D: Canvas 渐变球体 + 度数尺寸 + hover 光晕 + 选中粉色双环 + 曲线多边并行 + 自环 + 圆角标签 + 节点选中关联边高亮 + 边详情面板 + 实体类型图例 + 统计栏 + 路径发现/连接/推理演示/布局切换 + 搜索高亮 + 筛选

3D: Three.js 球体 + SpriteText + 粒子流动 + 主题适配

---

## 升级点

### U1: 边类型着色 + 置信度宽度映射 -- P0

按 `link.meta.kind` 着色（entity_relation 蓝 / event_entity 紫 / entity_entity 青），按 confidence 映射线宽。在图例中增加关系类型分段。涉及 `graph-viewer.tsx`, `graph-legend.tsx`。

### U2: 自环组详情展开 -- P0

参考 GraphPanel.vue 的 expandable self-loop list：检测自环边 → Header + count → 可展开列表（UUID/Fact/Type/Created/Episodes）。涉及 `page.tsx` 边详情面板。

### U3: 导出 PNG/SVG -- P1

调用 canvas `toDataURL` 或 `toBlob`。浮动控件增加导出按钮。涉及 `page.tsx`, `graph-viewer.tsx`。

### U4: 全屏模式 -- P1

Fullscreen API 或 CSS 全屏覆盖。ESC 退出。涉及 `page.tsx`。

### U5: Minimap 缩略图 -- P1

右下角 120x90 小 Canvas，渲染全部节点 + 视口矩形，可点击跳转。新增 `graph-minimap.tsx`。

### U6: 3D 功能对齐 -- P2

移植 2D 的选中高亮/边点击/搜索高亮/缩放控件/拖拽到 3D。涉及 `force-graph-3d.tsx`, `page.tsx`。

### U7: 深色模式适配(2D) -- P1

2D canvas 硬编码浅色值 → 根据 theme 切换。涉及 `graph-viewer.tsx`, `page.tsx`。

### U8: 节点右键菜单 -- P2

右键弹出上下文菜单（展开邻居/查找路径/连接/对话/来源/删除）。涉及 `graph-viewer.tsx`, `page.tsx`。

### U9: 布局过渡动画 -- P2

切换布局时平滑过渡（cooldownTime 或节点位置插值动画）。涉及 `graph-viewer.tsx`。

### U10: KG 构建状态指示 -- P1

查询 KG extraction 状态 → 底部居中 breathing hint 胶囊。参考 GraphPanel.vue `.graph-building-hint`。涉及 `page.tsx`。

---

## 建议实施顺序

**Phase 1 (1 周)**: U1 (边着色), U2 (自环组), U4 (全屏), U10 (状态指示)

**Phase 2 (1-2 周)**: U3 (导出), U5 (Minimap), U7 (深色模式)

**Phase 3 (2-3 周)**: U6 (3D 对齐), U8 (右键菜单), U9 (布局动画)
