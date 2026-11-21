# Agent Note: 报告 HTML 属性不输出反斜杠转义

Status: implemented

## Problem

报告的四个 HTML helper 在 15 段硬编码属性字面量里输出 32 对 U+005C U+0022。HTML 不以反斜杠转义属性引号，因此生成的 class／style 值不能对应已有 CSS，部分相邻属性也会被错误解释。实际 dataset slices、rag-audit HTML 与 ZIP bundle 直接消费这些 helper；该字符不是动态数据所需的 escape。

## Decision

仅从这 15 段已逐项核对的 HTML 属性字面量删除 32 个多余的运行时反斜杠。引号、动态 FormattedValue 与 escape 调用、DOM 结构、原 CSS 选择器／样式、文案、脱敏、业务数据和序列化均保持。修复不扩展到文件内其他字符串、JSON 或业务正则。

Root 独立用 stdlib AST 与 codepoints 证明每个引号前恰好一个实际 U+005C，并核对 reports API 直接 text/html Response 与两类 renderer 调用链后批准。该缺陷与后续仅类型／内部值风格整理分开提交。

## Alternatives considered

- 全文件或全仓替换反斜杠引号可以省步骤，但会触及 JSON、业务字符串或合法源码转义。这里只使用四个实际 helper、固定 15 段源位置与解析后字面量白名单。
- 添加 CSS 以匹配错误 class 可以让部分表格看起来恢复，却会把无效属性留在产物中，不能修正 style 或相邻属性。直接修正已确认的硬编码输出字符。

## Consequences

这几处 HTML 属性能对应已有样式，输出结构和内容继续沿用原规则。字面量更短，但不会绕过用户数据转义，也不建立额外 renderer 或兼容层。

整模块文本只允许这 15 行源转义投影，以及该段较短 f-string 所需的唯一 Ruff 分组括号折叠；完整 AST 只允许这 32 个字面量字符退出。所有 FormattedValue、escape 调用与其他节点保持一致。Ruff、格式、Python 3.11 AST、diff 和笔记门禁通过；没有运行 HTML generator、renderer、浏览器、应用、SDK、模型、数据库、服务、回调、业务正则或 Python 测试。

活跃笔记中的[结构化记忆换行修复](2026-11-05-structured-memory-newline-splitting.md)也是字面量生产者问题，但持有不同模块与输入语义；本篇不改变其决定。没有同一报告属性输出 owner 的既有提案需要吸收或归档。
