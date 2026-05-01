# `/knowledge/quarantine` 隔离区前端调研 — 现状评估 + 自研深化

## Context

**触发场景**:用户从 `/knowledge/quarantine` 出发,要求对**隔离区前端**做全面调研,**约束:不引大包优先自研**。这是 RAG 安全合规的"中转站"——OutputGuard 拦截的可疑文档、parse-risk 不达标的、敏感信息超阈值的、ACL 不明的等先入隔离区,人工审核后决定释放/删除/打标签。

**问题**:`/knowledge/quarantine` 已极重(`page.tsx` **2114 行**!+ 2 个 source.test),用 TanStack Query + ConfirmDialog + Switch + Badge,**调用 `documentApi`** + `Document` / `DocumentPipelineOptions` 类型——基础设施完整,**但需对照 RAG 安全合规 plan + Pre-POC scanner + POC attribution 严格审视**:① 多源隔离归因(why quarantine)② 批量审核工作流(stage / approve / publish)③ Presidio 命中详情联动 ④ ACL 修正 UI ⑤ 隔离时序趋势 ⑥ 自动放行规则配置 ⑦ 客户合规报告导出 ⑧ 与 OutputGuard 失败案例联动。本调研对标 Microsoft Purview / DLP / 合规审核工具,**全部自研**。

---

## 1. 现状盘点

### 1.1 文件清单

| 文件 | 行数 | 角色 |
|---|---|---|
| `page.tsx` | **2114** | 主页面(过重,需拆) |
| `loading.tsx` / `error.tsx` | - | 状态壳 |
| `page.layout.source.test.ts` / `page.source.test.ts` | - | 测试 |

### 1.2 已具备能力(从 imports 推断)

- ✅ TanStack Query
- ✅ ConfirmDialog(危险操作确认)
- ✅ `getDocumentKind` from monitor-utils(与 ingestion 共享)
- ✅ Search input + Switch + Badge
- ✅ `documentApi` + `Document` / `DocumentPipelineOptions`
- ✅ `useDocumentView` store(集中状态)
- ⚠️ 2114 行**过重**

### 1.3 8+ 大缺口

1. ❌ **多源隔离归因**(为什么进隔离区:OutputGuard / parse-risk / Presidio / ACL / 用户标记)
2. ❌ **批量审核工作流**(stage 标记 → approve / reject → publish 释放)
3. ❌ **Presidio 命中详情**(每文档命中实体类型 / 上下文 / 严重度)
4. ❌ **ACL 修正 UI**(部门 / 用户组 / 标签批量修改)
5. ❌ **隔离时序趋势**(7d / 30d 隔离速率告警)
6. ❌ **自动放行规则**(满足条件自动 approve,减少人工)
7. ❌ **客户合规报告**(导出脱敏 HTML 给法务/合规审计)
8. ❌ **OutputGuard 案例联动**(对接 safety plan redteam_suite)
9. ❌ **过期清理策略**(>90 天未审 → 自动归档/删除)
10. ❌ **审核员工作量看板**(谁审了多少 / 通过率 / 平均耗时)

---

## 2. 业界对标(全部排除)

| 工具 | 借鉴点 | 排除 |
|---|---|---|
| **Microsoft Purview** | DLP 标杆 | 商业 SaaS |
| **Varonis** | 数据访问治理 | 商业 |
| **OneTrust** | 隐私合规 | 商业 |
| **Apache Ranger** | 数据 RBAC | 服务太重 |
| **Apache Atlas** | 数据治理 | 服务太重 |
| **OpenMetadata** | 数据目录 | 偏数据集成 |
| **Garak / Lakera** | LLM 安全 | safety plan 已规划 |

**结论**:全部自研,前端 ~2700 行覆盖。

---

## 3. P0 落地任务(2-3 周)

### 3.1 多源隔离归因(~400 行)

**新建** `web/components/quarantine/quarantine-source-attribution.tsx`:
- 5 类隔离来源:
  - `output_guard`(LLM 输出被守卫拦截)
  - `parse_risk`(parse-risk 不达标,对齐 Pre-POC plan)
  - `presidio_pii`(敏感信息超阈值)
  - `acl_unclear`(ACL 不明)
  - `user_flag`(用户手动标记)
- 饼图(echarts)+ 钻取列表
- 每类显示 top-5 文档 + 推荐处理

### 3.2 批量审核工作流(~600 行)

**新建** `web/components/quarantine/review-workflow-panel.tsx`:
- 三态:`pending` / `staged` / `approved` / `rejected`
- 批量 staging:勾选多文档 → 标记 stage(暂存)
- 二次确认:reviewer 审核 staging → approve / reject
- 发布:approved 文档释放回 dataset
- 审计 log:每次操作记录 reviewer + reason + timestamp
- 后端:`app/services/quarantine_review_service.py`(新)

### 3.3 Presidio 命中详情(~350 行)

**新建** `web/components/quarantine/presidio-hits-panel.tsx`:
- 每文档展开:命中实体列表
  - 类型(身份证 / 手机 / 邮箱 / 银行卡)
  - 位置(page / line / char offset)
  - 上下文 50 字
  - 严重度(High / Medium / Low)
- 三选项:`保留 + 标签` / `脱敏 + 释放` / `删除整段`
- 与 Pre-POC plan 待审核列表共享 UI

### 3.4 ACL 修正 UI(~400 行)

**新建** `web/components/quarantine/acl-correction-panel.tsx`:
- 选中文档 → 当前 ACL 显示
- 批量修改:部门 / 用户组 / 标签
- 影响预览:修改后哪些用户能看到
- 集成 `app/services/document_permission_service.py`

### 3.5 隔离时序趋势(~250 行)

**新建** `web/components/quarantine/quarantine-trend-chart.tsx`:
- 折线图:每日新增隔离数 / 已审核数 / 待审数
- 7d / 30d 移动平均
- 隔离速率突增告警(可能是新 parser bug)
- 与 `feedback-trend-chart` 共享

### 3.6 自动放行规则(~400 行)

**新建** `web/components/quarantine/auto-release-rules.tsx`:
- 规则配置 UI:
  - "如果 Presidio 命中类型仅手机号 + 严重度 Low → 自动脱敏后释放"
  - "如果 parse-risk 是 Image_Heavy 但通过 OCR 重试 → 自动释放"
- 规则引擎:JSON DSL(简单 100 行 parser,自研)
- 模拟运行:看规则会自动放行多少文档
- 后端:`app/services/quarantine_auto_release.py`

### 3.7 客户合规报告导出(~350 行)

**新建** `web/components/quarantine/compliance-report-export.tsx`:
- 单文件 HTML(对齐 snapshot/precheck plan)
- 内容:
  - 隔离来源饼图
  - top-N 命中实体
  - 审核工作量统计
  - 审计 log(脱敏)
- 给法务 / 合规 / 审计拿走

### 3.8 拆 2114 行 page(~重构)

**重构** `page.tsx`(2114 → ~1000):
- 拆为:`quarantine-list.tsx` / `quarantine-stats-bar.tsx` / `quarantine-filter-toolbar.tsx` / `quarantine-detail-drawer.tsx`
- 严格保留 source.test 用例

---

## 4. P1 任务(1 月)

### 4.1 OutputGuard 案例联动
- 对接 safety plan redteam_suite.py
- 隔离区显示触发的 guard 类型 / prompt
- 反哺 guard 规则迭代

### 4.2 过期清理策略
- 90 天未审 → 归档 / 自动删除
- 90 天前提醒 reviewer
- 与 `regression_run_retention.py` 同源思路

### 4.3 审核员工作量看板
- 谁审了多少 / 通过率 / 平均耗时
- Cohen's κ(多 reviewer 一致性)
- 防止主观

### 4.4 隔离 → 数据集 / 删除追溯
- 一键查"这条隔离最终去了哪"

---

## 5. 关键文件

**重构**:
- `page.tsx`(2114 → ~1000,拆 4 个子组件)

**新建**(纯自研,~2900 行):
- `web/components/quarantine/quarantine-source-attribution.tsx`(P0)
- `web/components/quarantine/review-workflow-panel.tsx`(P0)
- `web/components/quarantine/presidio-hits-panel.tsx`(P0)
- `web/components/quarantine/acl-correction-panel.tsx`(P0)
- `web/components/quarantine/quarantine-trend-chart.tsx`(P0)
- `web/components/quarantine/auto-release-rules.tsx`(P0)
- `web/components/quarantine/compliance-report-export.tsx`(P0)
- `web/components/quarantine/quarantine-list.tsx`(P0,拆出)
- `web/components/quarantine/quarantine-stats-bar.tsx`(P0,拆出)
- `web/components/quarantine/quarantine-filter-toolbar.tsx`(P0,拆出)
- `web/components/quarantine/quarantine-detail-drawer.tsx`(P0,拆出)
- `app/services/quarantine_review_service.py`(后端 P0)
- `app/services/quarantine_auto_release.py`(后端 P0)

**复用**:
- `documentApi` / `Document` / `DocumentPipelineOptions`
- `useDocumentView` store
- `getDocumentKind` from `monitor-utils`(共享)
- Presidio(safety plan)
- `document_permission_service.py`
- snapshot plan HTML 报告框架

---

## 6. 验证

1. 多源归因:模拟 5 类隔离 → 饼图正确
2. 审核工作流:stage → approve → publish 链路打通
3. Presidio 详情:手机号 / 身份证命中带上下文
4. ACL 修正:批量改部门 → 影响用户预览正确
5. 自动规则:模拟 100 文档 → 自动放行 30
6. 合规报告:HTML 单文件含审计 log + 脱敏
7. 拆完后:`pnpm test` 现有 source.test 全过

---

## 7. 与已有调研协同

- **`rag-safety-compliance-deep-dive`**:OutputGuard / Presidio / Llama Guard 3 共享
- **`rag-pre-poc-scanner`**:Presidio 待审核列表共用 UI
- **`rag-poc-attribution-framework`**:差评 / 超纲案例可触发隔离
- **`rag-evaluation-deep-dive`**:redteam_suite 测试结果联动
- **`rag-kg-snapshot-deep-dive`**:HTML 报告 SSR 框架共享
- **`rag-feedback-frontend-deep-dive`**(刚完成):bad case 可手动加入隔离
- **`rag-ingestion-frontend-deep-dive`**(刚完成):入库失败可自动进隔离

---

## 8. 关键洞察

1. **2114 行 page 是技术债**:必须拆,审核工作流复杂度只会增加
2. **隔离区是合规护城河**:让客户法务 / 合规拿到报告就能签 = 销售加速
3. **不引大包**:Microsoft Purview / Apache Ranger 全套都不要,自研 11 组件 ~2900 行
4. **多源归因是诊断起点**:不分类的隔离区 = 黑洞,无法迭代
5. **批量审核工作流是企业刚需**:1000 隔离文档逐条人工 = 不可行,batch + 自动规则是正解
6. **审计 log 是合规底线**:谁审的、什么时候、什么理由必须可追溯
7. **自动放行规则是隐藏 ROI**:把简单 case 自动化,人工只看复杂的(对齐 POC plan LLM 辅助分工)

---

## 9. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口。

已落地:
- 隔离页已有紧凑 dashboard、inline 队列表筛选、右侧审核 drawer、summary cards、规则命中分布、疑似度/来源分布和快速操作。
- 审核动作已通过 documentApi 元数据回写支撑 release/retry/review/tune/delete 等必要流程,能完成“发现异常样本 → 人工复核 → 标记/重试/释放”的闭环。
- 现有 source tests 明确覆盖 compact header、queue filters、right-side review drawer 和页面布局约束。

明确不做:
- 暂不自建 Purview/Ranger 级 DLP/ACL 修正套件,也不新增隔离专属后端服务层。
- 暂不把自动放行规则、审核员绩效和合规报告全部产品化;这些需要真实审计要求后再开独立需求。

Directive: 隔离区保持异常样本审核中心定位,不要把完整合规治理平台塞进这个页面。
