# Embedding 与稠密候选检索命名验证

日期：2026-11-07。工作树：`C:/Users/jiahuanl/.codex/worktrees/style-task3-chat-tags/MimirQ`。

## 改动范围

本轮调整 6 个业务函数名称，涉及 8 个含命名引用的 Python 文件；另有 1 个配置文件只改说明注释，以及 2 个指南/索引文件更新。完整前后名称和位置见[映射记录](function-naming-round3-map.json)。

| 原名称 | 现名称 | 职责 |
| --- | --- | --- |
| `get_default_embedding_model` | `get_default_embedding_model_id` | 返回原有默认模型 ID 字符串。 |
| `test_embedding_model_status` | `probe_embedding_model_status` | 异步连接探针，返回原有状态结果。 |
| `test_all_embedding_models_status` | `probe_all_embedding_models_status` | 并发探测并生成状态汇总。 |
| `resolve_colbert_ann_provider_capability` | `resolve_colbert_retrieval_capability` | 解析提供方及语料上限状态。 |
| `ColbertIndexMixin._search_colbert_ann_docs` | `ColbertIndexMixin._search_colbert_dense_docs` | 对指定快照执行确定性稠密向量评分。 |
| `ColbertIndexMixin._search_colbert_ann` | `ColbertIndexMixin._search_colbert_dense` | 解析范围后调用上述查询路径。 |

`app.rag` 的懒导出、embedding 包导出、实际 corpus 通道、继承方法调用、测试 monkeypatch 和内部函数诊断标签同步。`select_embedding_model` 和 provider 的 `test_connection` 接口保持原有用途。

[候选检索指南](../guides/colbert_ann_retrieval.md)修正了已退出的 HF/Torch 提供方配置、旧 BM25 语料缓存来源和 ANN 描述。当前通道使用确定性哈希向量、有界发布语料快照和 NumPy 精确余弦 Top-K。已有 `ColbertAnnIndex` / `ColbertAnnIndexStore`、模块路径、`mimirq.colbert_ann_index.v1`、磁盘文件键及 `colbert_ann` trace 字段继续保持。

## 行为与验证

- 扩展回归覆盖 84 个后端测试文件：**808 项通过、63 项已记录基线排除**。运行前后核对 1833 个 Python 源文件，无变化。
- 本批 9 个 Python 文件通过 Python 3.11 解析、Ruff 和格式检查；本批空白检查通过。
- 完整 AST 在反向映射六个名称、去除说明字符串并规范化两处模块的 import 内符号排序后，与本批前快照一致。没有增加、删除或改变算法、参数、默认值、错误分支、返回结构及存储逻辑。
- 实际应用 OpenAPI 前后一致，共 358 条路径，并与现有前端输入一致。
- 离线提取实际 embedding 探针做前后对照：5 种单模型状态场景、1 种并发汇总及原默认模型 ID 一致。使用 stub 模型验证 available、unavailable、unsupported 和异常结果，没有调用真实 provider。
- 独立子进程验证实际包导出：导入 `app.rag` 时仍未加载 embedding；访问新探针时解析到实际相同函数。检查期间阻断 Torch、sentence-transformers、FAISS、Chroma 导入，没有触发这些依赖或请求 provider。临时签名键仅用于满足原有 Settings 导入校验。
- 本轮六个旧名称在应用、脚本、测试、插件、Docker、迁移和前端活跃源码中无引用；历史映射记录保留旧名称。
- 指南中的六个 `COLBERT_RETRIEVAL_*` 配置名称均存在于当前 Settings；已移除 HF 模型/设备/批大小/长度配置说明。
- 独立审查没有发现本批引入的 Critical、Important 或 Minor 问题，复核了 11 个源文件/指南的前后哈希、9 个 Python 文件 AST 和真实调用。其指出两处原有 builder 说明仍提到 HF/ANN，作者在收尾时补齐了相关说明字符串，并再次通过全文件 AST、Ruff 和格式检查；没有追加运行逻辑变动。[审查报告](E:/tmp/ragvia-function-naming-round3-20261107/final-review.md)保留审查当时的说明与范围。

## 基线及限制

业务修改前的 7 文件定向基线为 59 项通过、17 项沿用的基线排除。本轮没有新增排除项，最终 63 项仍来自前两批已记录的问题。具体文件与排除项见[测试选择记录](function-naming-round3-test-selection.json)。

本批保留既有 provider 不可用处理、模型 ID、单/批探针策略和候选回退行为。未新增兼容别名、兜底、重试或配置；没有真实 provider 连通性、外部向量库、数据库服务或生产质量验收。指南中的样例命令保留为回归入口，本轮没有执行该命令。

没有安装/卸载依赖、启动外部服务、改变用户数据、提交/暂存代码、移动 HEAD、发布或同步其他工作树。

## 复现记录

用具备项目依赖的 Python 环境，在该工作树根目录执行：

```python
import json
import subprocess
import sys
from pathlib import Path

selection = json.loads(
    Path("docs/development/function-naming-round3-test-selection.json").read_text(encoding="utf-8")
)
excluded = sorted({name.split("[", 1)[0] for name in selection["excluded_baseline_tests"]})
subprocess.run(
    [sys.executable, "-m", "pytest", "-q", *selection["files"], "-k", "not (" + " or ".join(excluded) + ")"],
    check=True,
)
```

本机解释器为 `E:/MimirQ/.venv/Scripts/python.exe`，Milvus SDK 验证源码通过 `PYTHONPATH=E:/tmp/ragvia-milvus-bm25-20261105/sdk` 提供。快照、映射、AST 对照脚本、可重跑的 `probe_checks.py`、实际接口导出、逐项日志和 task-only diff 位于 `E:/tmp/ragvia-function-naming-round3-20261107`。
