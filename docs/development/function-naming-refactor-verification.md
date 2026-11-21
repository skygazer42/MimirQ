# 函数命名整理验证

日期：2026-11-06。工作树：`C:/Users/jiahuanl/.codex/worktrees/style-task3-chat-tags/MimirQ`。

## 本批改动

审查建议落实到 63 个 Python 源码文件：19 个函数或方法改名，相关导入、调用、静态方法别名、导出列表和测试 monkeypatch 同步。具体位置及前后名称见[映射记录](function-naming-refactor-map.json)。

- 设置 RAG 校验覆盖重排与解析器，方法名改为 `_validate_rag_execution`；chat 和 regression 的单一重排校验保持原名。
- 通用分词统一使用 `tokenize_lexical_text` / `warmup_lexical_tokenizer`，私有 helper、内部缓存常量和 callable 别名同步；说明文字反映词法召回、重排、分块和数据库聊天记忆的现有用途。
- 缓存清理改为 `clear_derived_index_caches`，语料快照改为 `_resolve_derived_corpus_snapshot`。
- 通用文档对象删除和存储探针改为 `_delete_document_object` / `check_object_storage`。
- provider 拒绝检查改为 `reject_retired_provider`，窄范围的重排检查改为 `reject_retired_rerank_providers`。
- 装饰字符检测、合成样本接受评估和 KG 策略评估使用能表达实际返回值与职责的名称。

另删除 Sparse / ColBERT 中三个仅有定义、没有仓内直接引用或已注册动态消费者的私有 `*_after_bm25_upsert` 方法。当前 `CorpusIndex.upsert` / `remove` 继续通过 `_invalidate_derived_indexes` 失效派生索引，后续读取沿现有路径重建。

## 行为边界

函数体、参数、返回值与错误策略保持。`RetiredModelProviderError` 及子进程中的同名序列化类型、`BM25_TOKENIZE_*` 设置、`minio_health_check` 参数、公开健康字段和 HTTP 路由继续使用原有契约。真实 MinIO 专属操作、BM25 算法能力及已弃用的重排包装维持已确认的职责。

没有新增兼容别名、默认值、兜底、重试或配置，没有安装依赖、启动外部服务、修改用户数据、提交代码或同步其他工作树。

## 检查结果

- 最终 78 个后端文件：**767 项通过、62 项已记录基线排除**。最终运行前后核对 1833 个 Python 源文件，无变化。
- 63 个文件通过 Python 3.11 解析及 Ruff；60 个非第三方文件通过格式检查；本批 diff 空白检查通过。
- 将新名称反向映射、移除说明字符串并仅允许三个已核实的方法删除后，63 个文件的完整 AST 与本批前快照一致。算法、条件、输入检查、返回结构和异常处理没有额外变化。
- 五个增量行为批次分别通过 46、41、59、54、124 项，部分批次沿用已记录基线排除；这些批次相互重叠，不能相加为独立测试总数。
- 实际应用 OpenAPI 前后一致，共 358 条路径，并与当前前端 OpenAPI 输入一致。本批没有改变需要重新生成的前端接口契约。
- 旧改名符号及删除的 hook 在应用、脚本、测试、插件、Docker 和迁移 Python 源码中没有活跃引用。设置类外两个职责仍准确的同名重排 validator 单独保留。
- 独立审查复核了 63 个文件的修改前后哈希、AST、名称引用、调用绑定、错误序列化、缓存路径和接口导出，没有 Critical、Important 或 Minor 发现。[审查报告](E:/tmp/ragvia-function-naming-refactor-20261106/final-review.md)保留具体证据和范围限制。

## 已有基线限制

扩展基线在任何业务源码修改前运行，767 项通过，另有 5 项失败及沿用的 57 项排除。新增 5 项失败均有保存的修改前日志：

- 三项 KG diagnostics 夹具写死 `C:/data/temp34/MimirQ`，在当前工作树找不到源码路径。
- 两项旧批处理夹具调用已退出的 `apply_batch_lifecycle` / `delete_batch_documents`。

这些问题合并进[测试选择记录](function-naming-refactor-test-selection.json)的 62 项已知基线，不通过恢复旧 API、修改路径夹具或改动生产行为来掩盖。本记录证明本批命名整理的定向回归，不代表全仓 CI 或真实外部服务验收。

## 复现

使用已具备项目测试依赖的 Python 环境，在本工作树根目录执行：

```python
import json
import subprocess
import sys
from pathlib import Path

selection = json.loads(
    Path("docs/development/function-naming-refactor-test-selection.json").read_text(encoding="utf-8")
)
excluded = sorted({name.split("[", 1)[0] for name in selection["excluded_baseline_tests"]})
subprocess.run(
    [sys.executable, "-m", "pytest", "-q", *selection["files"], "-k", "not (" + " or ".join(excluded) + ")"],
    check=True,
)
```

本机解释器为 `E:/MimirQ/.venv/Scripts/python.exe`；Milvus SDK 验证源码通过 `PYTHONPATH=E:/tmp/ragvia-milvus-bm25-20261105/sdk` 提供。任务专属快照、改动 diff、逐批日志、完整 AST 对照脚本与接口导出位于 `E:/tmp/ragvia-function-naming-refactor-20261106`。

2026-11-07 的[后续整理](function-naming-followup-verification.md)继续调整配置启用、语料快照、字段归一化和状态记录的命名。上述结果保留为首批验证记录。
