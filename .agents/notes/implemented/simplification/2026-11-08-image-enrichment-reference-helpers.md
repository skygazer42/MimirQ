# Agent Note: 图片 enrichment 共享引用叶子规则

Status: implemented

## Problem

公式 OCR、图片代码、图片标题、VLM 标题和本地 OCR 重复维护完全相同的 HTML `<img>` 属性解析、file URL 规范化、本地文件有界读取与下一非空行查找。相同规则分散在多个 enrichment 模块，路径安全或错误原因调整容易遗漏副本。

## Decision

`app.parsing.enrich.image_references` 持有四类已证明同体的无状态叶子：HTML 图片解析、受限 file URL 规范化、返回原因码的本地文件读取，以及下一非空行查找。原模块按原私有名称导入这些函数；需要直接匹配 HTML 标签的标题模块同时导入共享 `HTML_IMAGE_TAG_RE`。

各 enrichment stage 继续拥有自己的 Markdown/reference 图片规则、候选判断、外部 HTTP 调用、图片生命周期、审计结果和输出顺序。`safe_read` 包装没有合并，因为 chart、formula、image-code 与 VLM 对 stat/read 失败和返回类型的政策并不完全相同。

VLM 与普通图片标题的同义引用扫描、已有标题判断和表格行判断直接复用 image_caption 中的实现。两者对非正 max_caption_chars 的清理政策不同，清理函数继续分别保留；不创建通用处理器。VLM 有界文件读取的重复叶子退出，safe 包装消费 image_references 的 bytes／reason 结果，仍按自己的合同只返回 bytes 或 None。image_ocr 真正使用的四项 image_code 绑定继续保留，单次拼接包装在实际调用处展开。

VLM 的通用 alt 正则使用实际单词边界及空白／数字规则，修复双反斜线使 image、chart、page N image 一直被误判为具体描述的问题。通用占位说明进入既有有界 caption 路径，具体 alt 仍直接使用；功能开关、图片／字节／字符预算、超时与 filename 降级保持。该修复改变错误的候选选择，不作为纯等价整理宣传。

## Alternatives considered

- 把整条图片 enrichment 统一成一个通用处理器可以删除更多代码，但会混合公式、二维码、OCR、图表和 VLM 的候选规则、错误原因与后端调用，不符合现有领域边界。
- 仅共享正则常量可以减少少量重复，但路径规范化和有界读取仍有多个完全同体实现，无法解决安全规则同步问题。

## Consequences

完全相同的路径与读取规则只有一个维护位置，同时保留每条 enrichment 链的真实差异。共享函数继续拒绝远程 file 主机、阻止 Windows file URL 前导斜线问题、执行大小上限，并沿用原 `stat_failed`／`read_failed`／`too_large` 原因。

验证比较旧函数 AST 与共享函数的代表输入／临时文件行为，核对所有导入与调用绑定，并运行 Ruff、格式和笔记门禁。按用户要求不运行 Python 测试、网络后端、MinIO 或真实图片处理。
