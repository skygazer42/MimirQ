# 函数命名后续整理验证

日期：2026-11-07。工作树：`C:/Users/jiahuanl/.codex/worktrees/style-task3-chat-tags/MimirQ`。

## 改动

延续上一批已完成的命名整理，对实际职责进一步核对后，调整 5 个业务函数和 1 个测试函数，涉及 13 个 Python 文件。调用、导入、导出及 monkeypatch 同步；完整位置见[映射记录](function-naming-followup-map.json)。

| 原名称 | 现名称 | 实际职责 |
| --- | --- | --- |
| `bm25_available` | `is_milvus_bm25_enabled` | 检查 BM25 和 Milvus 配置；不探测服务健康。 |
| `CorpusIndex.scope_documents` | `CorpusIndex.load_corpus_snapshot` | 按租户与文档/数据集范围读取发布语料快照并关闭会话。 |
| `CorpusIndex._load_retrieval_docs_for_rebuild` | `CorpusIndex._load_bounded_corpus_documents` | 查询快照和重建共享的文档加载；保留原计数及加载后上限检查。 |
| `critique_synthetic_sample` | `normalize_synthetic_sample_critique` | 复制样本、保留已有评语值、补齐缺失字段；不判断内容质量。 |
| `lotus_available` | `get_lotus_availability` | 返回带 `ok` / `reason` 的配置可用状态记录；不请求模型服务。 |
| `test_tokenize_for_bm25_expands_ascii_paths_versions_and_numeric_tokens` | `test_tokenize_lexical_text_expands_ascii_paths_versions_and_numeric_tokens` | 测试名与上一批通用分词职责一致。 |

函数参数、返回值、判定分支、原有默认值、注入参数和错误处理保持。`critic_fn` 仍可注入自定义评审；LOTUS 的既有失败处理、`RETRIEVAL_REBUILD_MAX_CHUNKS` 配置及异常信息保持。没有新增兼容包装、回退、重试、默认成功分支或新依赖。

## 验证

- 最终扩展回归覆盖 81 个后端测试文件：**796 项通过、63 项已记录基线排除**。运行前后核对 1833 个 Python 源文件，无变化。
- 13 个文件通过 Python 3.11 解析、Ruff、格式及本批空白检查。
- 完整文件 AST 对照在反向映射名称、排除说明字符串并规范化两个已核实模块的 import 内排序后完全一致；没有额外的逻辑或方法删除。
- 实际应用 OpenAPI 前后一致，共 358 条路径，并与现有前端输入一致。
- 离线提取实际函数做前后对照：6 种样本归一化输入、8 种 BM25 配置、8 种 LOTUS 配置和 4 种合成流水线场景结果相同。流水线使用固定时钟和确定性生成器，包括注入拒绝评审的场景；不执行真实模型、数据库或网络。样本输入未被归一化函数修改。这些探针不并入 pytest 数量。
- 本轮旧名称在应用、脚本、测试、插件、Docker、迁移和前端活跃源码中无引用。历史映射中的旧名称保留其原义。
- 独立审查复核了全部 13 个文件的前后哈希、完整 AST、实际调用、导出、默认函数和测试 patches，没有 Critical、Important 或 Minor 发现。详见[审查报告](E:/tmp/ragvia-function-naming-followup-20261107/final-review.md)；活跃源码引用与历史名称记录的范围分别以本页说明为准。

## 基线与范围

任何业务改名前运行的 8 文件基线为 74 项通过、1 项失败：`test_ask_dataset_table_masks_rows_before_answer_and_hides_sql` 的模拟查询结果缺少当前生产代码要求的 `planner_execution_mismatch` 字段。该项与前批 62 项基线合并为 63 项已知排除，没有为改名恢复旧接口或修改无关生产行为。

本批是内部命名整理，不代表全仓 CI、真实外部服务或生产质量验收。没有安装/卸载包、启动服务、修改用户数据、提交代码、移动 HEAD 或同步其他工作树。原有 `iter_*` 函数返回可迭代集合并不构成自动改名理由，这次没有统一更换它们。

## 复现记录

[测试选择记录](function-naming-followup-test-selection.json)包含实际 81 个文件和 63 项基线。使用项目 Python 环境，在本工作树根目录运行：

```python
import json
import subprocess
import sys
from pathlib import Path

selection = json.loads(
    Path("docs/development/function-naming-followup-test-selection.json").read_text(encoding="utf-8")
)
excluded = sorted({name.split("[", 1)[0] for name in selection["excluded_baseline_tests"]})
subprocess.run(
    [sys.executable, "-m", "pytest", "-q", *selection["files"], "-k", "not (" + " or ".join(excluded) + ")"],
    check=True,
)
```

本机使用 `E:/MimirQ/.venv/Scripts/python.exe` 和 `PYTHONPATH=E:/tmp/ragvia-milvus-bm25-20261105/sdk`。原始快照、引用记录、AST 对照脚本、测试日志、接口导出和 task-only diff 位于 `E:/tmp/ragvia-function-naming-followup-20261107`。

同日的[第三轮整理](function-naming-round3-verification.md)继续整理 embedding 探针、默认模型 ID 和确定性稠密候选检索的名称；本页保留第二轮的验证结果。
