# Ingestion 监控页 UI 增强设计

- **Date**: 2026-04-21
- **Owner**: skygazer42
- **Page**: `web/app/knowledge/ingestion/page-client.tsx` (`/knowledge/ingestion`)
- **Status**: Approved (brainstorming complete, awaiting plan)

## 1. 背景与动机

`/knowledge/ingestion` 是入库任务监控中心,当前已具备:状态卡片、Composed 趋势图(含置信带 + 线性预测)、错误 Treemap、状态过滤、键盘快捷键(⌘K / `/`)、自动刷新切换、Live/Snapshot 时间窗。源页面 1144 行。

外部评审给出 20 项 UI/UX 改进建议。其中 5 项已实现或部分实现(#2 置信带 / #5 Live-Snapshot 切换 / #11 键盘快捷键 / #14 Processing 脉动 / #15 Sticky 过滤器)。本设计覆盖其余 **15 项中筛选的 8 项核心子集**。

## 2. 目标与非目标

### 2.1 目标
实现以下 8 项功能并交付为 **单 PR**:

| 编号 | 项目 | 档位 |
|---|---|---|
| #1 | Live Velocity Indicator(docs/min ↔ MB/s 切换) | T1 |
| #3 | Treemap cell 点击过滤列表 | T1 |
| #4 | 5 张状态卡 inline sparkline | T1 |
| #19 | 空状态 Quick Start CTA | T1 |
| #6 | 批量操作栏(Retry / Cancel / Delete / Export) | T2 |
| #9 | 拖拽上传(自适应 dataset_id) | T2 |
| #7 | 阶段 Tooltip | T3 |
| #13 | Skeleton Loading | T3 |

### 2.2 非目标(明确不做)
- **#8** Contextual Error Resolution(需后端错误分类 API)
- **#10** Priority Tagging(需后端 `user_pinned` 字段)
- **#12** 完整 Toast Batching(仅在 #6/#9 内做简版批次汇总)
- **#16** Monospace Metadata / **#17** Glow / **#18** Glassmorphism 微调(留下一轮 polish PR)
- **#20** Performance Mode 开关(已被 `motion-reduce:` 类覆盖)
- 后端字段新增(全部基于现有 API)
- 抽离任何与本任务无关的现有逻辑

## 3. 架构

### 3.1 文件组织

```
web/components/ingestion/
  stat-card.tsx              新,~120 行,sparkline 内联
  live-velocity.tsx          新,~90 行,docs/min ↔ MB/s 切换
  error-treemap.tsx          新,~110 行,onClick 透出 reason key
  bulk-action-bar.tsx        新,~160 行,4 按钮 + 选中计数
  drop-zone.tsx              新,~180 行,全屏 overlay + 自适应确认 dialog
  empty-state.tsx            新,~70 行,truly-empty CTA
  ingestion-detail-dialog.tsx 不动(504 行)

web/app/knowledge/ingestion/
  page-client.tsx            精简为编排,~750 行(1144 - ~500 抽离 + ~100 新 state)
```

### 3.2 状态所有权

`page-client.tsx` 持有(新增):

| State | 类型 | 用途 |
|---|---|---|
| `selection` | `Set<string>` | 选中的 docId |
| `reasonFilter` | `string \| null` | Treemap 点击后的过滤 key |
| `velocityUnit` | `'docs' \| 'bytes'` | 速度单位,localStorage `mimirq.ingestion.velocityUnit` 持久化 |
| `dropConfirmOpen` | `boolean` | 自适应 dialog 开关 |
| `pendingDropFiles` | `File[] \| null` | 拖入但 dataset_id 未定时缓存 |

子组件全部 props 接受,**不内部持有跨页面 state**。

### 3.3 数据流

- `useQuery(['ingestion-documents', status])` 不变,仍返回 `documents`
- `useQuery(['ingestion-dashboard', dashboardWindow])` 不变,仍返回 `dashboard.timeseries / top_error_reasons`
- 派生 `filtered`:`documents` → 现有 search → 新增 reasonFilter `(d) => !reasonFilter || (d.error_message ?? '').includes(reasonFilter)`
- Velocity 数据派生:见 §4.1
- Sparkline 数据派生:见 §4.3

### 3.4 API 调用清单

全部已存在,**零后端工作**:

```ts
documentApi.retry(id)
documentApi.cancel(id)
documentApi.delete(id)
documentApi.upload(file, { parser_backend, chunk_strategy, dataset_id, pipeline })
documentApi.uploadBatch(files, opts)
```

批量并发策略:`Promise.allSettled` + 并发上限 4(自实现 `pAllLimit`,~20 行,放在组件内或 `lib/utils`)。

## 4. 功能详设

### 4.1 #1 Live Velocity Indicator

**位置**:`PageScaffold` description 槽内,紧跟 "运行正常" pill 之后,显示为可点击 chip。

**单位切换**:点击 chip 切换 `docs/min ↔ MB/s`,持久化到 localStorage。

**docs/min 计算**:
```
最近 5 个 timeseries bucket 的 (completed + failed + quarantined) 总和
÷ (5 × bucket_minutes)
```
取自 `realChartData` 末 5 行,bucket 间距由 `ts[1] - ts[0]` 推导。

**MB/s 计算(诚实近似)**:
- 后端 timeseries 不带 bytes 维度。前端用 `documents.filter(d => d.status === 'completed')` 取最新 N 条 `file_size`,与对应 `processed_at` (若可用) 或 fallback 用 timeseries 时间窗近似,得 MB/s
- chip 文案明确标 "近 ~5 min 均值",避免误导
- 若 `processed_at` 字段不存在,只能用全窗口平均(粒度低),需在文案上更模糊化为"窗口均值"

**Empty 行为**:无 timeseries 数据时显示 `--`,不报错。

### 4.2 #3 Interactive Error Treemap

**交互**:`<Treemap onClick>` 接收 cell payload `{ name, size }`,设 `reasonFilter = name`。

**视觉反馈**:
- 选中 cell 加白色描边 + 加深 opacity
- 顶部新增 chip:`按原因过滤: <name> × 关闭`(在现有 search 输入旁)
- chip 关闭按钮清空 `reasonFilter`

**过滤逻辑**(注:`top_error_reasons` 的 key 是后端聚合的子串/类别,Document 上是 `error_message`):
```ts
filtered.filter(d => (d.error_message ?? '').includes(reasonFilter))
```
若全文无匹配则进入零命中分支(见 §6)。

### 4.3 #4 Sparklines in Stat Cards

**位置**:每张 `StatCard` 右下角,80×24 inline SVG,无第三方库。

**数据映射**:
| 卡片 | 时序数据来源 | 处理 |
|---|---|---|
| 等待队列 | (无) | **占位**:1 条灰色虚线 |
| 正在处理 | (无) | **占位**:1 条灰色虚线 |
| 已完成 | `timeseries.completed` | 真实 sparkline,绿色 |
| 失败/隔离 | `timeseries.failed + quarantined` 逐 bucket 加和 | 真实 sparkline,红色 |
| 总存储量 | (无累计 bytes 时序) | **占位**:1 条灰色虚线 |

**诚实原则**:不存在的数据不伪造;3 张占位卡的虚线明显区别于真实 sparkline,引导用户感知"此卡只看当前值"。

**实现**:`<svg viewBox="0 0 80 24"><path d={pathData}/></svg>`,pathData 用 `useMemo` 缓存,依赖 timeseries 数组引用。

### 4.4 #6 Bulk Action Bar

**触发**:列表行首加 checkbox(列宽 32px),表头加全选/清空。`selection.size >= 1` 时 fixed 底部 bar 滑入。

**布局**:
```
[选中 N 项] [清空] | [Retry] [Cancel] [Delete] [Export ▾]
```

**按钮启用规则**:
| 按钮 | 启用条件 |
|---|---|
| Retry | 选中包含 `failed` 或 `cancelled` 状态 |
| Cancel | 选中包含 `pending` 或 `processing` 状态 |
| Delete | 任意选中即可 |
| Export | 任意选中即可 |

**Delete 确认**:`Dialog` 弹出,要求用户输入选中数量数字(例如选了 7 个就要输 "7")才启用确认按钮。仿 GitHub 删 repo。

**Export**:client-side CSV 生成(`Blob` + `download` link),字段 `id, filename, status, file_size, current_stage, error_message, created_at, processed_at`。

**并发策略**:`pAllLimit(4)` 串行 4 路并发,`Promise.allSettled` 收集结果,末尾汇总 toast `成功 X / 失败 Y`,失败列表可点击展开(简版 #12)。

**ESC 键**:清空 selection。

### 4.5 #7 Stage Tooltip

**实现**:wrap 现有 `current_stage` badge 用 `@/components/ui/tooltip`。

**文案 map**:
```ts
const STAGE_TOOLTIPS: Record<typeof STAGE_KEYS[number], string> = {
  queued:    '等待调度,即将开始处理',
  parsing:   '通过 OCR / 解析器提取文本',
  chunking:  '按语义切分文档为可检索片段',
  embedding: '向量化与索引构建中',
  completed: '已可被检索',
}
```

**a11y**:`@/components/ui/tooltip` 已支持键盘聚焦显示。

### 4.6 #9 Drag-and-Drop Ingestion

**事件绑定**:document-level `dragenter / dragover / dragleave / drop`,在 `useEffect` 内挂载,卸载清理。

**计数器去抖**:用 `useRef<number>(0)`,`dragenter` ++,`dragleave` --,`> 0` 时显示 overlay。避免子元素切换导致 leave 闪烁。

**Overlay**:全屏 `fixed inset-0` + 毛玻璃 + 中心虚线框,提示 "拖入文件以开始入库"。`aria-live="polite"` 宣告 "拖入 N 个文件"。

**文件类型校验**:`event.dataTransfer.types.includes('Files')`,否则 overlay 显示红色 "仅支持文件"。

**自适应 dataset_id**:
```
读 URL search params 的 dataset_id:
  存在 → 直接 documentApi.uploadBatch(files, { dataset_id })
  缺失 → 弹 Dialog 让用户选 dataset(SelectInput 拉 datasetApi.list)+ parser_backend(默认 localStorage 偏好)
```

**进度反馈**:上传后 `queryClient.invalidateQueries(['ingestion-documents'])` 触发新数据,任务自动进入列表。Per-file 失败 toast,末尾汇总。

### 4.7 #13 Skeleton Loading

**触发条件**:`isLoading && !data`(首次加载)。

**结构**:替换 `PageLoading`,内部按真实布局 1:1 复刻骨架:
- 5 张 stat card → 5 个 `h-32 rounded-2xl bg-muted/50 animate-pulse`
- ComposedChart → `h-[400px] rounded-2xl bg-muted/50 animate-pulse`
- Treemap → `h-[280px] aspect-square rounded-2xl bg-muted/50 animate-pulse`
- Task list → 8 行 `h-14 rounded-lg bg-muted/40 animate-pulse`

**避免闪烁**:`useQuery` 配 `keepPreviousData: true`(切过滤器时不显示 skeleton)。

### 4.8 #19 Empty State Quick Start

**触发条件**:`documents.length === 0 && !isLoading`(truly-empty)。

**区分 filter-empty**:`documents.length > 0 && filtered.length === 0` 时显示不同 UI("无匹配,清除过滤器")。

**Truly-empty UI**:
```
🗂 (大图 icon)
"还没有任何入库任务"
三个 CTA 横排:
  [上传首个文档]   → 触发 drop-zone 文件选择 (input[type=file] 隐藏)
  [查看示例样本]   → 跳转 /docs/samples 或 trigger 内置示例
  [查看上手文档]   → 跳转 /docs/ingestion
```

## 5. 状态管理实现细节

### 5.1 Selection Set 操作
```ts
const toggleSelect = (id: string) =>
  setSelection(prev => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

const selectAllInPage = () => setSelection(new Set(filtered.map(d => d.id)))
const clearSelection = () => setSelection(new Set())
```

### 5.2 ESC 键解除
现有 `useEffect` keydown handler 已存在,在其中追加 `event.key === 'Escape'` 分支调用 `clearSelection`。

### 5.3 Velocity Unit 持久化
```ts
const [velocityUnit, setVelocityUnit] = useState<'docs' | 'bytes'>(() => {
  if (typeof window === 'undefined') return 'docs'
  return (localStorage.getItem('mimirq.ingestion.velocityUnit') as any) ?? 'docs'
})
useEffect(() => {
  localStorage.setItem('mimirq.ingestion.velocityUnit', velocityUnit)
}, [velocityUnit])
```

## 6. 错误处理

| 场景 | 处理 |
|---|---|
| 批量动作部分失败 | `Promise.allSettled` + 汇总 toast,失败列表可展开 |
| Delete 误触 | Dialog 要求输入选中数字才启用提交 |
| Upload 失败 | per-file toast + 末尾批次汇总(简版 #12) |
| Drop 非文件类型 | overlay 文字切红 "仅支持文件" |
| Reason filter 零命中 | 列表区显示 "无匹配,点此清除过滤" CTA |
| MB/s 数据缺失 | 显示 `--`,不报错 |
| Velocity timeseries 空 | 显示 `--`,不报错 |
| API 失败时切回 prev state | 已有 `setQueryData` optimistic 模式继承 |

## 7. 性能考虑

- **Sparkline**:纯 SVG path,`useMemo` 按 timeseries 引用缓存,无 D3/Recharts overhead
- **Selection**:`Set<string>` 而非 array,避免 O(n) 查找
- **Drop listener**:绑 `document` 一次,counter-based 状态更新避免 re-paint 抖动
- **Skeleton**:CSS `animate-pulse` 无 JS
- **Treemap onClick**:不触发 list re-render storm,`reasonFilter` 是单一 state 变更
- **`keepPreviousData: true`**:避免切过滤器时 skeleton 闪现

## 8. 可访问性

| 元素 | 处理 |
|---|---|
| Bulk bar | `role="toolbar"` + `aria-label="批量操作"` |
| Drop overlay | `aria-live="polite"` 宣告文件数 |
| Velocity toggle | `<button aria-pressed>` |
| Stage tooltip | `@/components/ui/tooltip` 默认键盘聚焦显示 |
| Delete confirm | `@/components/ui/dialog` 默认 focus trap |
| Checkbox | `<label htmlFor>` 关联 |
| Sparkline | `aria-hidden="true"`(纯装饰) |

保留所有现有 `motion-reduce:` 类。

## 9. 测试策略

沿用现有 `*.source.test.ts` 约定(源码模式断言,非 render):

| 新增/更新文件 | 关键断言 |
|---|---|
| `web/components/ingestion/stat-card.source.test.ts` | sparkline 分支:有 timeseries 走 path,无走占位虚线 |
| `web/components/ingestion/live-velocity.source.test.ts` | unit toggle 切换;localStorage key `mimirq.ingestion.velocityUnit` 正确 |
| `web/components/ingestion/error-treemap.source.test.ts` | onClick 回调签名正确;接受 cell payload |
| `web/components/ingestion/bulk-action-bar.source.test.ts` | Retry/Cancel 按状态启用规则;Delete 数字匹配启用 |
| `web/components/ingestion/drop-zone.source.test.ts` | counter-based dragenter/leave;dataset_id 自适应分支 |
| `web/components/ingestion/empty-state.source.test.ts` | truly-empty vs filter-empty 分支 |
| `web/app/knowledge/ingestion/page-client.task-cards.source.test.ts`(更新) | 新增 checkbox / selection 引用 |

## 10. 风险与待办

| 风险 | 严重度 | 缓解 |
|---|---|---|
| `top_error_reasons` 的 key 与 `error_message` 子串模糊匹配可能误命中 | 中 | 实现时观察,必要时改为后端加 `error_reason` 枚举字段 |
| MB/s 数据源粗糙(缺事件时间) | 中 | UI 文案标 "近似",必要时整体下线 MB/s 档保留 docs/min |
| `page-client.tsx` 拆分可能触发 Jest snapshot stale | 低 | 实施后跑 `pnpm test -u` 更新或排查回归 |
| 拖拽全局 listener 与其他页面 drop 冲突 | 低 | 仅在本页 mount 期间挂载,unmount 清理 |

## 11. Rollout

- **单 PR**,无 feature flag
- 本地 QA:8 项手工核对(包含拖拽 / Bulk Delete 数字确认 / Treemap → 列表过滤回环 / Skeleton 首屏 / Velocity 切换 / Tooltip 键盘聚焦)
- 验证命令:`pnpm verify`(lint + ui-check + typecheck + test + api-check)
- 回滚 = `git revert`

## 12. Out of Scope(明确不做)

- 后端字段新增(error_reason 枚举 / processed_at / cumulative_bytes_per_bucket)
- Toast 库替换(继续用 `sonner`)
- 抽离与本任务无关的现有逻辑
- Mobile 适配(本页明确为桌面 dashboard)
- 实时 WebSocket 推送(仍用 5s polling)
