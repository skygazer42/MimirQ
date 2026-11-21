# 文档处理、入库与溯源的显式缺省验证

> 历史验证记录：此处“改写为显式条件”的规则已由[直接传值契约](../../.agents/notes/implemented/simplification/2026-11-07-direct-value-contracts.md)更正。下列数量和语法检查结果不代表当前待修改项；独立的资源与零值修复仍有效。

日期：2026-11-07。工作树：`C:/Users/jiahuanl/.codex/worktrees/style-task3-chat-tags/MimirQ`。

## 本轮改动

延续用户禁止 `x or None` 及可空参数 `value or default` 的规则，处理前两批之外的文档访问、身份与溯源、入库/索引审计、表格存储和解析 processor 流程。35 个所有者文件共 **198 处表达式**：193 处直接归空或可空参数回退，另有 5 处本地可空整数生产者。源码/测试范围及排除项见[检查选择记录](explicit-null-documents-test-selection.json)。

- 已提供的数据集对象不因布尔值为假而被重复查询；dataset 与 document 两层 ACL 检查的顺序及拒绝传播保持。
- 元数据和 snapshot 映射保留实际内容及 `0` / `False` 字段。溯源版本 cap、哈希格式、输入复制和安全字段投影保持。
- parse-quality 证据及质量分数保留；VLM 判断仍先检查显式启用状态，不新增模型调用。
- 索引状态时间及命中统计的显式 datetime 时钟不被系统时钟覆盖；缺失才使用原默认。
- `_first_int` / `_to_int` 的 5 处已确认可空返回值使用显式判断，生产者只求值一次，整数零保留。
- provider 空文本、scope 默认、checkpoint、重试、事务和错误处理保持原业务规则；没有新增通用包装、兼容别名、重试或配置。

本轮与前批合并的 148 个选定文件通过直接 literal-None/可空参数规则检查，本轮 5 处整数生产者也单独覆盖。检查不代表全仓所有可空属性、动态值和第三方代码已完成数据流分析。

## 行为与静态证据

- 修改前 10 个相关测试文件为 172 项通过、4 项失败、1 项集成条件跳过。四项旧夹具失败在产品源码修改前已记录。
- 新增 13 项真实所有者行为用例先复现 9 项失败、4 项正常对照；改写后全部通过。覆盖假值 dataset 的查找/两层 ACL/403、映射内容与输入不变性、隐私投影、质量零分与启用门、实际本地 JSONL 时钟过滤和非 PostgreSQL 索引 upsert 时间。
- 初次完整 113 文件运行有 1134 项通过、2 项跳过、76 项基线排除；36 个本批源码/测试文件在该运行期间未变化。
- 审查时 35 个完整生产模块 AST 只包含198处获准条件改写，没有其他代码变化；Python 3.11 解析与运行时语法编译、Ruff、格式和空白检查通过。
- 独立审查未发现 Critical、Important 或 Minor 问题。其独立完整 AST 比对核查216个条件：93个 None-only、123个业务空值判断；96个新增求值绑定无名称冲突或 comprehension 逃逸，生产者及分支顺序保持。
- 独立提取实际纯函数，在固定 build/time/embedding/settings 依赖下进行了79组身份、去重、执行标识、完整溯源快照、版本 cap及隐私投影对照，普通有效输入结果与所有哈希相同；假值 Mapping 的快照与同内容普通映射一致。
- 实际 API 为358条路径，与当前前端输入、前批及审查版本一致；126篇 note 的目录、格式、相对链接及归档门禁通过。PyCharm指定文件构建返回成功，但构建诊断收集能力有限，只作补充证据。

## 并行修改与当前交付验证

初次测试结束后，六个同范围文件有并行修改。本任务没有覆盖它们：已按review.diff和修改前字节重建全部36份审查/测试版本并逐份验证SHA256，独立保存并行差异。当前源码与审查版本的24处额外 AST 差异均只是同对象的 `getattr(..., declared_field, default)` 改为直接读取该声明字段；198处本轮条件、生产者和周围结构保持。

当前共享版本第一次复验只有一项夹具失败：独立修改后的文档生命周期代码读取已声明的 `doc_metadata`，而“畸形存储 URI 不得删除”测试对象缺少该字段。本任务仅为这个旧测试对象增加 `doc_metadata={}`，完整测试模块 AST 证明所有生产调用、原断言和异常预期未变。没有恢复默认属性读取或放宽生产保护，随后相关生命周期与新增行为用例合计26项通过；完整113文件复验为 **1134项通过、2项跳过、76项基线排除**。

这次完整运行期间，索引通道文件又进行并行简化，随后索引审计也同步复用现有帮助函数。此后另行验证了最新版本：原内联错误归一化与新函数的7组值结果一致，最新索引通道/索引审计/生命周期/新增用例 **39项通过、1项集成跳过**；37个本轮源码/测试文件在这次增量验证期间及收尾核对时没有变化。没有把完整1134项运行描述为与最后一次并行编辑逐字节相同的版本。

原198处审查包、第一阶段24处字段读取差异、后续索引帮助函数简化与最新源码哈希分别保留，避免把其他工作归为本轮修改。[审查报告](E:/tmp/ragvia-explicit-null-documents-20261107/final-review.md)审查的是不可变的198处包；最新共享版本由作者的字段差异证明、当前规则/静态检查和必要的增量测试覆盖。

## 基线与平台范围

当前选择有76项已记录基线排除：前批72项加上修改前就失败的4项旧夹具。三项仍 patch 已移动的 `document_processing.settings`，一项仍 patch 手工文档路由以前的导入所有者。没有为这些基线恢复旧入口或放宽行为；当前补齐的 `doc_metadata` 夹具没有增加排除项。

两项跳过分别需要Windows不支持的fork语义和未启用的索引通道集成条件。测试采用本地会话/文件和服务替身，不代表真实PostgreSQL并发、对象存储、OCR/VLM/LLM或生产检索质量验收。

## 复现与记录

在该工作树根目录，用已具备项目测试依赖的Python环境执行：

```python
import json
import subprocess
import sys
from pathlib import Path

selection = json.loads(
    Path("docs/development/explicit-null-documents-test-selection.json").read_text(encoding="utf-8")
)
excluded = sorted({name.split("[", 1)[0] for name in selection["excluded_baseline_tests"]})
subprocess.run(
    [sys.executable, "-m", "pytest", "-q", *selection["files"], "-k", "not (" + " or ".join(excluded) + ")"],
    check=True,
)
```

本机使用 `E:/MimirQ/.venv/Scripts/python.exe` 和 `PYTHONPATH=E:/tmp/ragvia-milvus-bm25-20261105/sdk`。精确快照、198处清单、纯本轮diff、并行字段差异、规则/完整AST检查、红绿日志、API导出和最终交付记录位于 `E:/tmp/ragvia-explicit-null-documents-20261107`。决定沿用并更新[显式缺省记录](../../.agents/notes/implemented/simplification/2026-11-07-explicit-null-fallback.md)。

本任务没有暂存/提交、reset/checkout、安装/卸载依赖、运行外部服务、改变用户数据、发布部署或同步其他工作树。共享工作区的独立修改与提交保持，任务边界由快照及源码哈希界定。
