# 防御性兜底代码清理 (Defensive Fallback Cleanup) 2026-Q2

> 创建日期:2026-05-29
> 触发:用户要求"全面看问题写到 plans,毫无意义的兜底代码也要清理"
> 原则:**fail-fast > silent-fallback**。兜底代码掩盖真实故障,让系统在错误状态下静默继续,调用方拿到空/假数据以为正常——这比直接报错危害更大。

---

## Context

`fullstack-code-audit-60items` 已清零 `except: pass`(吞异常什么都不做)。但**另一类反模式未被系统覆盖**:`except Exception: return None/[]/{}`——catch 宽异常后**静默返回默认值不抛不记**,掩盖真实 bug。量化:

| 模式 | 数量 | 60-items 是否覆盖 |
|---|---|---|
| `except` 后静默 return 默认值(`[]/{}/None/0/False`) | **457** | ❌ 未覆盖 |
| 其中 `except + return None` | 199 | ❌ |
| `getattr(settings, ..., default)` | 2413 | ❌ |
| 软依赖 `except ImportError` | 54 | 部分(合理,保留) |
| 前端 `catch { return null }` 吞错误 | ~多处 | ❌ |
| `'demo'` 假数据兜底 | 28 | ❌ |

**目标**:清理掩盖故障的有害兜底,改为显式失败/降级;保留合理降级(软依赖、UI 空态)。不是无脑删所有兜底——**关键是区分**。

---

## 判定准则(清理前必读,避免误删合理降级)

### 🔴 有害兜底(必清 → 改 fail-fast 或显式降级)
1. `except Exception:` 宽异常后 `return None/[]/{}` **不 log 不抛**,掩盖核心链路失败
2. 用 `'demo'` / 假数据 / 占位默认掩盖"未配置 / 未登录 / 未授权"
3. `getattr(settings, X, default)` 当 X 是**必填配置**时(返回默认掩盖配置缺失)
4. 前端 `catch { return null }` 让 UI 显示"空数据"而非"加载失败"
5. 永不触发的死 fallback 分支

### 🟢 合理降级(保留,别误清)
1. 软依赖:`try import gliner/sentry except ImportError: 功能禁用`(**有 warning 日志**)
2. UI 初始空态:`metadata ?? {}` 这类明确无业务风险的默认
3. 文档化的业务默认值(settings 类里定义的默认,非 getattr 兜底)
4. 明确"降级到备用"语义且有日志的(如 LLM fallback 链)

**一句话判定**:兜底后**调用方能否区分"成功但空" vs "失败"**?不能区分 = 有害。

---

## 分级清理清单(具体 file:line,来自代码挖掘)

### P0-A 核心检索链路掩盖失败(最危险,影响所有 RAG 查询)

| 位置 | 现状 | 危害 | 清理 |
|---|---|---|---|
| `app/rag/engine.py:577-580` | `except Exception: return []` 查询解析失败 | 检索跳过查询扩展,LLM 异常被吞 | log warning + 降级到原始 query,不返回空 |
| `app/rag/retriever.py:282-284` | `except: return []` 实体分区键解析失败 | 跳过实体过滤,可能返回**超大结果集** | log + 降级全局分区,显式标记 |
| `app/rag/retrieval/orchestrator.py:1244-1246` | `except: return []` KG 块注入失败 | 客户端**假成功**(以为 KG 块已加) | 在 meta 记录失败原因,不静默空 |
| `app/rag/engine.py:408` | `getattr(settings,"LLM_API_BASE","")` | 空字符串掩盖未配置 LLM | 必填项 fail-fast(启动校验) |

### P0-B 安全 / 数据丢失风险

| 位置 | 现状 | 危害 | 清理 |
|---|---|---|---|
| `web/lib/auth-headers.ts:21` | dev 模式 `'demo'` userId,生产 undefined | NODE_ENV 误判 → 全路由到 demo 用户,跨租户 | 收紧:仅显式 flag 开启 demo,否则不注入 |
| `app/api/v1/feedback.py:73,82,147` | 3 处 `except: return None` | 用户反馈**静默丢失**(以为已存) | 失败返回明确状态 + 错误日志 |
| `web/app/knowledge/ingestion/page-client.tsx:1724` | demo 模式 URL 参数激活无鉴权 | 跨租户访问 demo 数据 | 仅 dev/test 部署启用 |

### P1-A API 层 catch 后静默 return None(调用方无法区分错误)

`connectors_external.py:85` / `chunk_presets.py:99` / `parsing.py:440` / `document_assets.py:350` / `connectors_db_catalog.py:42` / `observability.py:622` —— 模式统一:`except Exception: return None`。

**清理范式**:收窄异常类型(`ValueError`→400/422,存储异常→502/503),其余向上传播;或返回带 error 字段的结构而非裸 None。

### P1-B getattr 配置兜底分类清理

- **冗余兜底**(settings 类已有默认):删 getattr 默认值,直接 `settings.X`
- **掩盖配置缺失**(必填项):移到 `app/core/config.py` 的启动校验,缺失即 fail-fast
- 热点:`app/rag/engine.py`(13+ getattr defaults)

### P2 前端 catch 吞错误 → 错误态

`ingestion/page-client.tsx:1778,1792` 等 `catch { return null }` → 返回 `{ error }` 状态对象,UI 区分"加载中(null)"vs"加载失败(error)",显示错误提示而非空数据。

---

## 保留白名单(明确不动,防误清)

- `app/__init__.py:24,36,148` 等 `except ImportError: pass`(可选模块软依赖)
- `app/parsing/parsers/etl4llm_parser.py:124` Pillow 不可用降级(有 warning)
- LLM/embedding 的 fallback 降级链(有明确降级语义 + 日志)
- UI 初始空态默认(`?? {}` / `?? []` 无业务风险的)

---

## 守卫(防回退,套用 60-items 的 source-guard test 模式)

新增 source-guard 测试(参考已有 `tests/test_logging_get_logger_source.py` / `test_datetime_now_utc_source.py`):

1. **`tests/test_no_silent_broad_except_source.py`**:扫 `app/rag/{engine,retriever,retrieval}` 核心链路,禁止 `except Exception:` 后直接 `return None/[]/{}` 不 log 不 raise。白名单显式列出已审查的合理降级。
2. **`web/lib/auth-headers.source.test.ts`**:锁住 demo userId 仅在显式 flag 下注入。
3. **eslint**:开 `@typescript-eslint/no-floating-promises`(60-items H3 也提到),并加规则禁止 `catch { return null }` 无注释。

---

## 分批落地次序

| 批次 | 范围 | 工作量 | 风险 |
|---|---|---|---|
| 批 1(P0-A) | 3 处核心检索链路 + LLM_API_BASE 校验 | 1 天 | 中(改热路径,需测试网) |
| 批 2(P0-B) | auth demo + feedback 数据丢失 + ingestion demo | 1 天 | 低 |
| 批 3(P1-A) | ~6 个 API 路由 catch return None | 2 天 | 低 |
| 批 4(P1-B) | getattr 分类:冗余删 / 必填移启动校验 | 2-3 天 | 中(2413 处,先做 engine 热点) |
| 批 5(P2 + 守卫) | 前端 catch 错误态 + source-guard test | 2 天 | 低 |

**合计 ~8 天**。批 1+2(P0)是止血,2 天可见效。

---

## 验证

1. 每批后跑 `make verify`(后端 lint + test)+ `pnpm verify`(前端)
2. 批 1 核心链路:故意触发解析/检索异常,确认现在**显式报错/降级日志**而非静默空结果
3. 批 2:生产构建确认无 demo userId 注入;feedback 失败返回明确状态
4. source-guard test 全绿,锁定不回退
5. 清理后重新量化:`except + return 默认值` 从 457 显著下降(核心链路归零)

---

## 与既有 plan 边界

- 60-items 清 `except: pass`(已 0);本 plan 清 `except: return 默认值`(457,不同反模式)
- `optimization-convergence-2026-q2.md` 的 A1(核心引擎拆分)与本 plan P0-A 同区域,**建议合并执行**:拆 engine/retriever/orchestrator 时顺手清掉其中的有害兜底

## 一句话

不是删所有兜底,是删**掩盖故障的兜底**——让 `except: return []` 这种"静默吞掉检索失败、调用方拿空数据以为正常"的代码改成 fail-fast 或显式降级。最危险的是 RAG 核心三件套(engine/retriever/orchestrator)的 `except: return []`,先清这 3 处止血。

---

## 🔬 2026-05-29 执行核实修正(重要:推翻了上面基于抽样的部分定性)

实际全项目扫描 + 逐处核实后,**上面 Part A 的定性被推翻**,记录如下:

### 量化(精确扫描)
- 全 `app/` **宽异常静默兜底**(`except Exception`/裸 `except` + `return None/[]/{}` + 无 log 无 raise):**271 处**
- 精确过滤(排除校验器 `_valid_*`/强转 `_coerce_*`/缓存/软依赖 import/可选增强降级)后:**66 处**
- 再逐处核验,**真正值得改的约 6 处**(审计删除 / 向量库查询 / ACL 应用类)

### 抽查结论:Part A 的"核心链路有害兜底"是**误判**
逐处读真实代码(非 agent 抽样),plan 点名的位置全部是**合理惯用防御**:
- `engine.py`:宽异常静默兜底实测 **0 处**(plan 说的 577-580 不存在)
- `retriever.py` / `orchestrator.py`:命中的是 `except (TypeError, ValueError, AttributeError)` **收窄类型**(tenant_uuid 解析等),属合理输入容错,**非** `except Exception` 掩盖检索失败
- `pii_anonymizer.py:56` = `_valid_ipv4` 校验器(return False=无效,合理)
- `path_safety.py:32` = 路径越界检测(异常=不安全,**安全机制本身**)
- `feedback.py:73/147` = `_coerce_uuid` 强转 / trace 查找辅助(合理)
- `pipeline.py:576` = GLiNER 软依赖降级(合理)

**结论**:本项目兜底写得**克制且惯用**,60-items 已清掉真正坏的 `except: pass`。真正"毫无意义的有害兜底"**极少**。盲目改 271/66 处会破坏大量合理的校验/强转/缓存/降级逻辑,**引入 bug**。

### 真正的问题不是"该删",而是"缺 log"
少数确实有害的(如 `audit_log_retention.py` 的审计删除失败 `return 0` 伪装"删 0 行")——其降级行为**正确**(docstring 明确"purge should never crash"),唯一问题是**静默无 log**,故障不可见。正确清理 = **补 log**,不是删兜底/改 fail-fast。

### 已执行
- ✅ `app/services/audit_log_retention.py`:补 `get_logger` + 5 处审计删除/候选查询静默吞补 `logger.warning`(保留 best-effort 降级);ruff 通过 + 8 测试通过
- 候选(同模式,可选):`storage/vector/milvus.py`(查询失败补 log)、`document_acl_provenance_service.py`(ACL 应用补 log)

### 治本建议(优于存量大改)
加 source-guard test:约束**新增**的宽异常静默兜底必须带 log 或显式 `# noqa` 豁免注释。存量保持(多为合理防御),只在改动相关文件时顺手补 log。
