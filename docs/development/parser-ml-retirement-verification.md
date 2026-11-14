# XGBoost、unstructured、腾讯云 SDK 退出验证

日期：2026-11-06。目标：`C:\Users\jiahuanl\.codex\worktrees\style-task3-chat-tags\MimirQ`。本记录说明本批范围，不代表全仓、真实模型服务或生产文档质量验收。

## 已完成检查

- 退出选择、历史读取、实际工厂/旧包装、后置排序和 PDF 初始化/合并规则的定向检查通过。相关失败先复现，再修复。
- 保留的解析发现、反馈/通用证据导出、离线评测等 46 项检查通过。
- 前端 5 个文件、42 项通过，覆盖设置旧 LTR 值显示、无自动换模型、证据工作台及数据集契约。相关 ESLint 通过。
- 审查修复后的最终后端回归覆盖 66 个文件：674 项通过、57 项已记录基线排除。运行前后核对 1833 个 Python 源文件哈希，均未变化。新增的旧预览夹具和旧别名查询所有者失败均在前批副本复现，没有放宽生产类型契约或重建旧模块导出以绕过。
- 实际应用 OpenAPI 导出和前端类型生成完成，LTR 训练导出接口不再出现。
- 审查修复后，45 个 Python 文件通过 Python 3.11 AST 兼容与 Ruff 检查，40 个非第三方文件通过格式检查。应用/脚本 AST 扫描没有 XGBoost、unstructured 或腾讯云 SDK 的活跃导入；移出的 9 个通用反馈定义与修改前 AST 一致。
- 再次从实际应用导出 358 条 API 路径，与当前前端 OpenAPI 输入一致；重新生成 TypeScript 后与已交付文件逐字节一致。
- 122 篇笔记的目录、格式、相对链接与归档门禁通过；本批 diff 空白检查通过。

## 定向回归复现

后端文件和排除项见[检查选择记录](parser-ml-retirement-test-selection.json)。排除项来自已有失败证据，不代表全仓检查通过。使用具有项目测试依赖的 Python 环境，在仓库根目录执行：

```python
import json
import subprocess
import sys
from pathlib import Path

selection = json.loads(
    Path("docs/development/parser-ml-retirement-test-selection.json").read_text(encoding="utf-8")
)
excluded = sorted({name.split("[", 1)[0] for name in selection["excluded_baseline_tests"]})
subprocess.run(
    [sys.executable, "-m", "pytest", "-q", *selection["files"], "-k", "not (" + " or ".join(excluded) + ")"],
    check=True,
)
```

本机使用 `E:/MimirQ/.venv/Scripts/python.exe`，Milvus SDK 验证源码通过 `PYTHONPATH=E:/tmp/ragvia-milvus-bm25-20261105/sdk` 提供，没有为此安装或启动服务。

## 现有检查限制

1154 个 tracked TypeScript 来源检查遇到成员管理测试夹具差异：`web/app/settings/access-admin-test-harness.tsx` 缺少新必需时间戳，`web/app/settings/rbac/members-model.test.ts` 和 `web/e2e/members-boundaries.spec.ts` 使用旧的 nullable 成员字段。这些文件与后端成员 schema 不属于本批；重新从当前实际 API 生成类型后暴露了差异，未修改相关业务或测试来掩盖。882 个生产来源的类型检查通过，六项 API/界面静态检查通过。

新增基线复现：`test_run_retrieval_parallel_variant_execution_preserves_public_query_order` 仍 monkeypatch 已退出的 `generate_alias_queries` 所有者；`test_ingestion_preview_accepts_sync_clean_preview` 用字典替代现行有类型的 PipelineEffective，缺少治理关键词字段。两者在前批独立副本中复现，并核对相关测试/生产函数与本批前一致。

第一次审查后整批运行有 672 项通过、2 项认证检查失败。认证源文件在该进程启动后被并行任务修改，已加载代码与磁盘源码不一致；新进程重跑该文件的 9 项全部通过。本批没有修改认证代码或为此新增排除项。随后最终整批运行通过，且源文件哈希无变化。

## 独立审查修复

独立审查确认三处重要缺口：系统设置和入库策略写入/激活仍可保存旧 TCADP 选择，预览子进程包装会把退出错误变成通用 500。先用 14 项失败复现，再补充配置导入/元数据写入边界；修复后，与保留的历史读取/导出/显式停用以及普通输入错误对照合计 102 项通过。

设置和数据集配置在修改前验证；入库策略复用实际元数据写入所有者，PUT/导入/回滚和配置包启用规则均拒绝旧值。共享归一化与历史解析不添加执行校验，避免容错读路径静默丢弃旧策略。文档、分块、pipeline 和 ingestion 预览的实际处理器识别序列化的退出异常，返回 HTTP 400 和可操作原因，普通服务故障仍按原来策略处理。

## 数据和执行边界

只删除仓库自带的三份已退出 XGBoost 权重，没有删除用户模型、索引、文档或历史记录；没有卸载原虚拟环境里的包。测试中替换 OCR/视觉资源，验证 PDF 不导入 XGBoost 和既有规则决策，不运行真实权重推理。没有启动或请求外部模型/解析服务，PDF 在有模型时与规则路径的质量差异需在部署样本上另行评估。
