# Agent Note: 退出未接入的解析辅助工具

Status: implemented

## Problem

行业噪声模式包与 LLM 噪声挖掘器只有包内导出、冻结测试和历史覆盖引用，没有接入生产步骤、API、脚本、动态注册或配置入口。两份写磁盘的清理文档函数也只有原 output 包导出／测试引用；实际文档下载只消费 Markdown 块转换和 DOCX 字节渲染。保留这些导出会把未接入能力混作在用流程。

## Decision

退出 app/parsing/preprocess/llm_noise_miner.py 及 industry_noise_patterns 下四个文件，不保留旧路径或开关。file_preprocessor 的十二个步骤白名单不变；实际在线清洗仍通过 clean_preview 中的 LLM 客户端与结构化请求运行，不消费退休 miner／profile。现用 document_noise_rules、watermark 链和实际小模型 Runtime 继续由原模块持有，不能根据相似名字扩大退出范围。

output 包只公开实际消费者使用的 markdown_to_blocks 和 render_clean_docx_bytes。块转换与 DOCX 渲染合在 docx_writer.py；退出只剩一个实际函数的 markdown_writer.py，以及没有生产调用的 write_clean_markdown／write_clean_docx。文档 API 仍从 output 导入原两个名字，下载路由、响应、块转换顺序、原始文本零值和渲染高亮参数保持。

这是无接入工具的实际退出；原文和 SHA 留在本批快照及历史 coverage，当前 app 清单移除退休路径，删除不计完成。冻结 Python 测试中的旧导入留待后续维护，不为它们保留生产包装。

## Alternatives considered

- 仅因 __all__ 声明而保留全部工具，能避免旧私有测试导入失败，但完整引用图没有显示真实生产或外部发布承诺，无法证明这些表面需要继续维护。
- 把行业模式重新接入清洗步骤可以使用现有实现，但这是新增业务接线，会改变十二步骤和实际 LLM 请求；本次不新增这条流程。
- 继续分开 Markdown 与 DOCX 文件便于按格式导航，但 Markdown 文件剩余职责只服务同一个下载入口，合回该能力可减少一次维护跳转。

## Consequences

未接入工具和在用步骤清楚分开，文档下载的两个生产导入保持。实际 Tiny ONNX、OCR、文件预处理和在线清洗没有退出。相邻[辅助生产者边界](2026-11-05-parsing-auxiliary-producer-boundaries.md)、[图片共享规则](2026-11-08-image-enrichment-reference-helpers.md)与[质量结果所有者](2026-11-13-parse-quality-decision-owner.md)保留各自决定，本篇只收窄无调用工具；检索未发现同题活动提案需要归档。

验证结合完整引用图、原步骤白名单、实际 API 消费端、有限 AST／假文档渲染／模型端口及完整应用冷导入。没有运行 Python 应用测试、真实文件写入、DOCX 处理、模型、LLM 或服务；不能据此声称实际文档保真和环境验证通过。
