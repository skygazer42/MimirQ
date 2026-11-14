# Agent Note: 运维导出遵守实际字节与文件边界

Status: implemented

## Problem

密钥遮盖保留前后各四字符，长度为八的密钥虽然插入星号，全部原字符仍可恢复。JSONL tail 在 stat 后无界 read，文件继续增长时能突破 max_bytes。事故包会写入空对象文件，manifest.files 却因 bool({}) 报告它不存在。

## Decision

长度不超过八字符的密钥使用既有全遮盖形式，其他长度与字段范围保持。只用字面量验证规则，不读取真实密钥。

JSONL 文件按已捕获 stat 计算原起点后使用 read(limit)，让单次读取始终服从原预算；保原残行、JSON 解码和错误旁路。truncated 仍表示该次 stat 对应的快照，不增加锁、再次 stat 或追赶增长的读取循环。

事故包的六个 manifest.files 标记使用 payload is not None，与实际写入条件一致。None 仍不生成条目，空对象仍写入真实的 {} 文件；schema、文件名、JSON 内容和顺序保持，不把存在性改成非空内容质量判断。

metrics flush 直接使用实际 redact owner，已归一化审计／freshness payload 直接消费。三个同体标签清理规则共用一个参数化私有函数，三个 pattern、长度和七个实际调用绑定保持，不新增指标、模式或故障回退框架。

## Alternatives considered

- 继续给八字符密钥保留首尾能与九字符外观一致，但没有隐藏任何原字符，因此使用原短密钥遮盖规则。
- 对增长文件反复重读更接近“最新尾部”，却不再有固定 IO 预算；保留有界快照语义。
- 将空对象文件也删除可以让原 false 标记成立，但空 JSON 是合法诊断结果；修正存在性标记，保留真实产物。

## Consequences

八字符密钥不再完整可恢复，追加写入不能突破读取字节预算，manifest 能准确描述空文件内容的存在。读取不保证得到并发追加后的最新尾部；没有修改 retention、事务、指标错误隔离或实际日志格式。

验证使用实际函数源码和内存 Path／file／ZIP 端口，独立核对 Unicode 边界、增长及换行、空／非空／缺省条目、先 redact 后写入和 freshness 边界；资源及维护 SQL 只核对源码。没有执行应用测试、真实 ZIP／文件、PII 正则、数据库事务、SDK、网络、OS 锁或线程，不把端口证据称为生产 IO 验收。
