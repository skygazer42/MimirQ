# Advanced RAG Features & Expert Workbench Plan

## 2. 交互式数据调优 (Data-Driven Refinement)

### 2.1 向量空间诊断 (Embedding Space Diagnostics)
- [ ] **3D 投影预览**: 集成 `react-force-graph-3d`，在 `similarity-workbench` 中渲染当前查询周边的向量簇分布。
- [ ] **异常点标注 (Outlier Detection)**: 在图谱中高亮显示那些得分极高但内容不相关的“幻觉干扰项”，并支持一键“禁用”或“标记”。

### 2.2 闭环标注工作流 (Closed-loop Labeling)
- [ ] **专家反馈闭环**: 在聊天页面和工作台集成快捷评价系统，标注结果同步至后端的 `evidence-workbench` 供模型迭代。
- [ ] **快速修正面板**: 允许专家直接在 UI 上修改错误的分块边界，并触发即时的局部重索引 (Incremental Re-indexing)。

## 4. 前端架构升级
- [ ] **动态导入优先级**: 根据用户角色（普通用户 vs 专家用户）动态调整组件加载优先级，避免专家级工作台代码影响普通用户的首屏性能。
