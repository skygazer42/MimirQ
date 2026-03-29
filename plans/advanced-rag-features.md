# Advanced RAG Features & Expert Workbench Plan

## 1. 深度溯源与透明化 (Traceability & Observability)

### 1.1 可视化检索流水线 (Interactive Pipeline Graph)
- [ ] **全链路时序图**: 将 `rag-trace-panel` 升级为可视化的交互流图，标记每一步的耗时（Latency）和召回数量。
- [ ] **Re-ranking 权重可视化**: 展示不同检索通道（BM25, Vector, Graph）在融合阶段的得分贡献，支持拖动滑块实时模拟权重变化对结果的影响。

### 1.2 A/B 测试对比视图 (Diff-centric Debugging)
- [ ] **侧边栏对比**: 支持双面板开启，对比“线上版本”与“测试配置”在同一问题下的检索召回差异。
- [ ] **语义差异高亮**: 对比两份切片结果的相似度偏差，高亮显示新增或丢失的关键证据。

## 2. 交互式数据调优 (Data-Driven Refinement)

### 2.1 向量空间诊断 (Embedding Space Diagnostics)
- [ ] **3D 投影预览**: 集成 `react-force-graph-3d`，在 `similarity-workbench` 中渲染当前查询周边的向量簇分布。
- [ ] **异常点标注 (Outlier Detection)**: 在图谱中高亮显示那些得分极高但内容不相关的“幻觉干扰项”，并支持一键“禁用”或“标记”。

### 2.2 闭环标注工作流 (Closed-loop Labeling)
- [ ] **专家反馈闭环**: 在聊天页面和工作台集成快捷评价系统，标注结果同步至后端的 `evidence-workbench` 供模型迭代。
- [ ] **快速修正面板**: 允许专家直接在 UI 上修改错误的分块边界，并触发即时的局部重索引 (Incremental Re-indexing)。

## 3. 极速感与专业交互 (Professional Velocity)

### 3.1 预取与缓存增强
- [ ] **持久化布局状态**: 记录用户在 `document-viewer` 中的滚动位置、缩放比例和高亮状态，即使刷新页面也能完美还原。

### 3.2 键盘优先工作流 (Power-user UX)
- [ ] **全局热键地图**: 实现类似 IDE 的快捷键系统（e.g. `G` 开头图谱、`D` 开头文档、`C` 开头对话）。
- [ ] **Vim 风格导航**: 在长列表（如切片搜索结果）中支持 `j/k` 快速切换和焦点跟随。

## 4. 前端架构升级
- [ ] **动态导入优先级**: 根据用户角色（普通用户 vs 专家用户）动态调整组件加载优先级，避免专家级工作台代码影响普通用户的首屏性能。
