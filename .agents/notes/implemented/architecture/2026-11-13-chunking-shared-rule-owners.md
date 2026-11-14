# Agent Note: 分块公共规则保留单一维护点

Status: implemented

## Problem

Auto 和 Manuscript 各自持有完全相同的 Markdown／JSON 检测函数和四条正则。两种策略的选择顺序和自适应能力又确实不同，把整条分派合并会改变业务规则。

本地 utils/splitters 的三个文件只由内部模块和 utils 公共包再导出，实际业务策略使用外部 langchain_text_splitters。没有生产、脚本、配置、动态注册或外部文档入口需要这份副本；冻结的 test_complexity_batch35.py 仍直接引用本地 Fixed 类，不能把它描述为全仓无人引用。

## Decision

两种策略直接使用现有 utils 公共包的 looks_like_json／looks_like_markdown。四条正则及两个函数体、签名和 JSON 异常政策按原始 AST 保持，只改变函数所属模块和公开名字。两份本地副本与多余 json／re 导入退出，不新增文件或旧私有别名。

Auto 保留自己的检测优先级、policy-manual 能力和自适应参数；Manuscript 保留原来的分阶段选择。实际 ABC、frozen capability 记录、带缓存的 lazy Mapping 和包级惰性导出各有真实职责，保持原字节。参数、标志、别名、公开类、缓存顺序和动态导入时点不按风格统一成无状态函数。

三个本地 splitter 文件及七个旧导出退出，utils 继续作为普通包提供真实层级分块与公共检测。零步长问题的有限假 codec 复现保存在 scout，因这份实现没有业务入口，不新增进度保护来继续维护它，也不改外部 LangChain 或冻结测试。

Document 的 metadata 是 BaseMedia 已验证的字典及默认工厂，两个策略直接读取；真实可空的 id 和原始 metadata 值继续保留。密度计算只有一个使用默认值的实际调用方，未使用的 sample_chars 覆盖参数退出，保持50,000字符采样、原公式、浮点运算及预算；bs 已经由 max(1, int(...)) 保证为正，删除不可能进入的 ratio 默认分支。

固定 regex、原生字符串与内部数值计算不把意外异常伪造成0、False或0.9，交给原调用方处理。JSON 检测仍按原启发式在解析失败时返回 False，这属于真实策略选择合同；不把它和内部已成立的数值／字符串操作混作同一失败规则。推荐标签从既有 capability 目录生成独立 set，保原公开名字与可变性，不让消费者的修改反向影响冻结目录。

本篇延续[结构化分块边界](../bug-fix/2026-11-05-structured-chunk-owner-contracts.md)保留不同策略的决定，仅共享确实相同的规则。原始 source-line span 与纯文本契约仍由[既有逐行所有者](../simplification/2026-11-08-chunker-source-lines.md)持有，不建立新的行模型副本。

## Alternatives considered

- 新建 content_detection.py 可以给两个函数单独的文件；现有 utils 已承担公共工具职责，退出旧 splitters 后无需另加模块。
- 合并 Auto／Manuscript 可以减少更多重复代码，但它们的顺序、policy-manual 支持和自适应处理不同；只移动已经证明完全相同的两个检测函数。
- 修复并保留本地 token 循环能满足旧测试及可能的未知调用方；实际业务没有使用这份副本，用户也已要求不为旧测试保留生产兼容层，因此退出无根实现。

## Consequences

两种策略的共同检测规则只有一个维护点，保持真实类型和配置状态。旧私有 detector 名称与本地 splitter 导入不再可用，冻结测试需要后续维护；删除路径不计作现存文件的完成数。

Root 已完成精确函数／正则 AST、全模块非 import 结构及声明导入差异核对；7项密度计算和12项假子切分器／原生 Document 对照保持输出、构造与选择调用轨迹，实际 Document 拒绝 metadata=None。Ruff、格式、Python 3.11 语法、内存编译和差异检查通过。这些有限检查不证明真实分块质量、SDK、模型、tokenizer、网络或数据库运行，Python 应用测试没有修改或执行。
