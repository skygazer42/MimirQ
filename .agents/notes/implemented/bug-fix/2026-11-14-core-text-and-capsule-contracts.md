# Agent Note: 核心文本坐标与签名按自身协议解释

Status: implemented

## Problem

casefold／lower 可能把一个 Unicode 字符展开成多个 codepoint。引用与 claim evidence 把转换后的索引直接用在原文，围绕错误位置取证；JSON fence 和 followup tag 搜索也因此切错内容。capsule verifier 还按外部 signature.value 的长度重算 HMAC，合法签名的一字符前缀也可能通过。

## Decision

citations 与 claim evidence 继续使用原 ASCII casefold／非 ASCII exact 匹配规则，但将找到的 folded 索引通过现有 text owner 的单份常量空间前缀遍历映回原文 codepoint，再比较首命中。保词顺序、窗口、text／term 预算与原数据，不建立全量字符映射缓存或改变 Unicode 规范化协议。

三处 backtick 查找直接在 raw 文本中进行，info string 继续 lower 并按原 allowlist 选择；不以 regex 替代线性扫描。followup tag 的搜索副本只做保持长度的 ASCII A-Z 到 a-z 转换，原 body／问题、大小写 tag、limit、去重与未闭合规则保持。

capsule v1 只接受 native signer 的固定 48hex 协议，并固定按 48 重算；外部输入不决定校验位数。非空但错长或内容不匹配的签名沿原 signature_mismatch 失败；缺值仍为 signature_value_missing，缺 secret、schema／alg 和 feature gate 仍按原 reason 与顺序处理。不新增状态码、regex 框架或可选弱校验模式。

## Alternatives considered

- 对所有文本只用 ASCII lower 能保住索引，却会丢掉已有的词匹配语义；只映回真实索引，搜索规则保留。
- 保存每字符 folded 映射表能直接查坐标，但会为大文本增加缓存与内存维护；只在需要时做前缀遍历。
- 为 verifier 增加最小长度仍允许外部选择安全位数；使用 signer 已有的固定长度。

## Consequences

证据窗口与协议内容重新对应原文，合法 index 0 与 Unicode 展开后的首命中保留。短签名不再通过，畸形值也不变成服务器异常；没有读真实签名密钥或更换签名 schema。

原公开入口错误与修后 Unicode、混合词、fence、tag、固定签名／feature-gate 场景分别留存。验证使用 literal、严格 tokenizer／position／verifier 端口和实际源代码，没有运行真实模型、NLP／regex 资源、SDK、API、数据库、网络或应用测试；不宣称浏览器 UTF-16 坐标或所有自然语言等价匹配已经另行实现。
