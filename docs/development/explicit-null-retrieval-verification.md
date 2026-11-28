# 检索、缓存与运行资源的显式缺省验证

> 历史验证记录：此处“改写为显式条件”的规则已由[直接传值契约](../../.agents/notes/implemented/simplification/2026-11-07-direct-value-contracts.md)更正。下列数量和语法检查结果不代表当前待修改项；独立的资源与零值修复仍有效。

日期：2026-11-07。工作树：`C:/Users/jiahuanl/.codex/worktrees/style-task3-chat-tags/MimirQ`。

## 本轮范围

延续用户禁止 `x or None` 及可空参数 `value or default` 的规则，继续整理上一批之外的检索上下文、候选/语义缓存、corpus token、共享 Redis slot、运行准入/预热和证据锚点所有者。

45 个既有 Python 文件共 149 处表达式：148 处直接 literal-None 或可空参数回退，另有一处返回类型已明确可空的真实 retriever 选择。新增一个包含 13 个行为用例的测试文件。具体源码与测试范围见[检查选择记录](explicit-null-retrieval-test-selection.json)。

## 处理语义

- 显式提供的 Redis 启用回调、参数 mapping、embedding runtime 和取消事件不会因为自身布尔值为假而被替换。参数中的 `0` / `False` 保留。
- 真实 retriever 仅在返回 `None` 时使用既有 shim；原有导入失败处理和 shim 类型不变。
- 语义缓存维护的 epoch `0` 保持零时刻；scan `0` 执行原有最小一条约束，`None` 才选择缺省扫描量。
- 证据缺口 helper 的显式空锚点列表表示不做可选锚点检查，`None` 仍选择默认字段。必须召回模式的上游解析器仍会补默认字段；其完整函数 AST 与本轮前一致，实际 caller 的启用/禁用路径均有覆盖。
- 空字符串 provider、空范围及 scope 默认策略保留其既有业务含义。计算型表达式只求值一次，后续分支保持惰性，没有新增通用包装、重试、配置或失败转成功策略。

本批不代表全仓所有可空属性/动态结果都完成数据流分析，未选定文件与第三方代码保持原状。普通 `value is None or invalid` 逻辑判断仍然有效。

## 验证

- 修改前 8 个相关测试文件有 48 项通过。
- 新增行为用例先复现 9 项失败、2 项正常对照；修复后连同实际 contextual-gap caller 的 2 项模式对照，共 13 项通过。
- 完整 45 模块的 Python 3.11 AST 仅包含获准的 148 处条件改写及一处真实 retriever 缺省选择语句；46 个源码/测试文件通过 Ruff、格式、运行时语法编译和本批空白检查。
- 当前批次与前批合并的 113 个选定文件通过规则检查，未发现直接 literal-None OR 或可空参数 OR；检查包含 union、Optional 和带引号的可空标注。
- 实际 API 导出仍为 358 条路径，与当前前端输入和前批实际 schema 一致。
- 126 篇 note 的目录、格式、相对链接与归档门禁通过。PyCharm 指定文件构建返回成功，但构建消息收集能力有限，仅作为补充证据。
- 独立审查确认 46 份前后哈希、45 模块改写范围和 55 个新增绑定；独立提取实际 cache-key 函数进行 81 组候选缓存、9 组语义缓存对照，键均保持一致，另有 11 组租户/账户/数据集/文档/pipeline/behavior 隔离对照保持区分。
- 最终 102 文件定向回归为 **949 项通过、1 项平台跳过、72 项已记录基线排除**。本轮 46 个源码/测试文件的哈希在运行期间无变化；没有为基线失败恢复旧导出或放宽查询边界。

[审查报告](E:/tmp/ragvia-explicit-null-continuation-20261107/final-review.md)未发现可操作源码问题，保留了当时回归尚待基线分类的验收限制；作者后续复现及最终验证分别留有日志。语义决定沿用并更新[显式缺省记录](../../.agents/notes/implemented/simplification/2026-11-07-explicit-null-fallback.md)。

## 基线与平台限制

初次 102 文件扩展运行有 949 项通过、6 项失败、1 项平台跳过及 66 项已知排除。六项失败都在旧 singleflight 夹具：五项仍 monkeypatch 已移动的 `retriever.emit_stream_event`，一项仍 patch 旧检索入口，最终访问了未准备的 dataset runtime 行。

独立测试进程通过只读源码 import loader 使用本批前保存的实际模块，六项相同失败全部复现。`app/rag/retriever.py` 所有者还与前批验证完成时的哈希一致；没有恢复旧导出、放宽必需的 runtime 查询或修改 fixture 来掩盖。因此检查选择记录共包含 72 项已复现/记录基线排除。跳过项需要 `fork`，在本 Windows 环境不适用。

本记录只证明此定向选择的行为，不代表全仓 CI、真实 Redis/数据库/向量库或生产检索质量验收。测试使用服务替身与本地会话，不启动外部服务。

## 复现

在该工作树根目录，用已有项目依赖的 Python 环境运行：

```python
import json
import subprocess
import sys
from pathlib import Path

selection = json.loads(
    Path("docs/development/explicit-null-retrieval-test-selection.json").read_text(encoding="utf-8")
)
excluded = sorted({name.split("[", 1)[0] for name in selection["excluded_baseline_tests"]})
subprocess.run(
    [sys.executable, "-m", "pytest", "-q", *selection["files"], "-k", "not (" + " or ".join(excluded) + ")"],
    check=True,
)
```

本机解释器为 `E:/MimirQ/.venv/Scripts/python.exe`，Milvus SDK 验证源码由 `PYTHONPATH=E:/tmp/ragvia-milvus-bm25-20261105/sdk` 提供。快照、149 处清单、规则/AST 检查、红绿日志、六项基线复现、实际接口导出和 task-only diff 保留于 `E:/tmp/ragvia-explicit-null-continuation-20261107`。

本任务没有暂存/提交代码、移动 HEAD、同步其他工作树、安装/卸载包、请求外部服务、修改用户数据或发布部署。期间共享工作树的独立入库服务提交使 HEAD 前进，该提交与本轮源码范围无交集，已保留；本轮验证始终以保存的源码快照和实际文件哈希为准。

同日的[文档与入库后续整理](explicit-null-documents-verification.md)继续处理相关所有者；本页保留检索批次的验证结果。
