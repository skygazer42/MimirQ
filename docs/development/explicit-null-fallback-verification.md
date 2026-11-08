# 显式缺省与空值判断验证

> 历史验证记录：此处“改写为显式条件”的规则已由[直接传值契约](../../.agents/notes/implemented/simplification/2026-11-07-direct-value-contracts.md)更正。下列数量和语法检查结果不代表当前待修改项；独立的资源与零值修复仍有效。

日期：2026-11-07。工作树：`C:/Users/jiahuanl/.codex/worktrees/style-task3-chat-tags/MimirQ`。

用户明确禁止两类写法：`x or None` / `None or x`，以及可空参数的 `value or default`，要求使用显式判断。

## 本批范围与结果

本批清理当前 68 个已修改的自有 Python/测试文件中的 228 处表达式，包括 84 处直接带 `None` 的 OR、144 处引用可空函数参数的 OR。检查识别普通 union、`Optional[T]` 和带引号的可空注解。选定文件和测试记录见[检查选择](explicit-null-fallback-test-selection.json)。新增 1 个行为回归文件，共 69 个源码文件参与验证。

- 缺省依赖通过 `is None` 选择，合法但布尔值为假的 scorer、embedder 等注入对象保留。
- 社区摘要的可空 LLM 客户端注解使用引号，补充检查后同样通过显式缺失判断，已有客户端不会触发重复创建。
- 空字符串回到已配置 provider、空范围沿既有默认 scope、空文本/集合归空等业务规则单独表达，保留其原有含义。
- 复杂生产表达式只求值一次；后续 fallback 保持惰性，没有引入通用包装、重试、新默认配置或静默恢复。
- 显式 sparse 同义词字典直接创建轻量编码器，避免空字典被 raw 配置或配置缓存覆盖；未提供字典时继续使用原配置缓存和锁。
- 本地及 Redis 限流器只有 `burst_size is None` 才计算默认容量，显式 `0` 不再被替换为默认突发容量。

普通 `value is None or invalid` 是逻辑判断，不属于值回退。本轮没有把未改动仓库文件、第三方/vendor 代码和未做数据流证明的属性/动态结果统一改写，因此不代表全仓所有可空值的 `or` 已清零。后续在这些调用链新增或修改代码时沿用同一规则。

## 验证证据

- 修改前 7 文件既有行为基线：36 项通过。
- 假值注入与显式同义词场景先复现 4 项失败、1 项正常对照；零容量场景另复现 2 项失败。带引号的 LLM 客户端注解检查又复现 1 项失败及 1 项正常对照。修复后的新增回归合计 14 项通过，包含 `None` / `0` / `False` / 空字符串的规范化对照。
- 最终 90 文件定向回归：**860 项通过、66 项已记录基线排除**；69 个本批源码文件的哈希在运行期间无变化。
- 69 个文件通过 Ruff、格式、Python 3.11 AST 解析及运行时语法编译，本批 diff 空白检查通过。68 个既有完整模块的 AST 只包含获准的表达式改写与五项已记录的局部调整。
- AST 规则检查在选定 68 个文件中未发现直接 literal-None OR 或可空参数 OR；检查区分可空类型/默认值、真值选择与普通 `None` 比较逻辑。
- 独立审查确认 69 份修改前后哈希，77 个新增局部求值绑定没有名称/导入/global 冲突，也没有落在 lambda/comprehension 绑定范围。400 组独立对照保留了直接归空链的结果身份和生产者调用顺序。没有 Critical、Important 或可操作的 Minor 发现。
- 实际 API 导出仍为 358 条路径，与当前前端输入及上一轮实际 schema 相同；125 篇 note 的目录、格式、相对链接及归档门禁通过。
- PyCharm 指定文件构建返回成功，但提示构建诊断收集能力有限，作为补充证据；主要结论由 Python 静态、行为与源码检查支持。

[独立审查报告](E:/tmp/ragvia-explicit-null-fallback-20261107/final-review.md)保留初版 227 项的具体范围及未验证项。收尾补查发现的带引号 LLM 参数已在作者修复轮补齐，另用失败/通过回归、完整 AST 和最终整批检查验证。已知业务取舍见[设计记录](../../.agents/notes/implemented/simplification/2026-11-07-explicit-null-fallback.md)。

## 基线限制

首轮扩展检查有 858 项通过、3 项失败，另沿用 63 项先前已记录的排除。这 3 项旧融合 profile 测试仍要求 `cross_encoder` 自动回退。用本批前保存的 guard/profile 完整源码在独立测试进程中运行同一组测试，三项失败均复现，因此合并为 66 项已知基线，没有恢复已退出的 provider 或放宽执行边界。

首轮运行期间两个无关的 dataset analysis 文件发生并行修改，已单独记录；本轮 69 个文件保持一致。最终运行只对本批源码稳定性作出结论，不代替其他并行改动的验收。860 项通过是该定向选择的结果，不代表全仓 CI 或部署服务验收。

## 复现

使用已有测试依赖的 Python 环境，在该工作树根目录执行：

```python
import json
import subprocess
import sys
from pathlib import Path

selection = json.loads(
    Path("docs/development/explicit-null-fallback-test-selection.json").read_text(encoding="utf-8")
)
excluded = sorted({name.split("[", 1)[0] for name in selection["excluded_baseline_tests"]})
subprocess.run(
    [sys.executable, "-m", "pytest", "-q", *selection["files"], "-k", "not (" + " or ".join(excluded) + ")"],
    check=True,
)
```

本机使用 `E:/MimirQ/.venv/Scripts/python.exe`；Milvus SDK 验证源码由 `PYTHONPATH=E:/tmp/ragvia-milvus-bm25-20261105/sdk` 提供。原始快照、规则检查器、完整 AST 对照、红/绿日志、baseline 复现、API 导出与 task-only diff 保留于 `E:/tmp/ragvia-explicit-null-fallback-20261107`。

没有安装/卸载依赖、请求外部服务、改变用户数据、暂存/提交代码、移动 HEAD、发布或同步其他工作树。

同日继续处理的检索、缓存与运行资源范围见[后续验证](explicit-null-retrieval-verification.md)；本页保留首批结果。
