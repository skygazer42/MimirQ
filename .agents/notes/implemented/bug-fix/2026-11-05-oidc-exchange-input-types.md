# Agent Note: OIDC exchange 的原始字段类型

Status: implemented

## Problem

服务端 exchange 把 req.json 的结果断言为字符串字段，再直接执行 trim 或 String。实际 JSON 的 code、code_verifier 和 provider_id 可以是数字、对象或数组；redirect_uri 的对象还可用自有 toString 字段阻止原始值转换。这些输入在同源检查后抛出未捕获 TypeError，没有返回入口既有的请求错误响应。

## Decision

入口将四个原始字段标成 unknown，先验证非 null 字段必须为字符串，再按原规则 trim 和解析 redirect URI。类型不符返回 no-store 的 invalid_request 和 400，且不联系身份提供方。缺少或 null 的输入继续走原 missing_code_or_verifier 路径；正常字符串、长度限制、同源检查、提供方选择、token 请求、错误映射和 Cookie 策略保持。

## Verification

受控 NextRequest、真实 route 和 Response 的四个非法字段用例在固定原始实现上均因 TypeError 失败，原成功／跨源和新增缺少输入对照通过。修复后相同用例通过；请求只在外部 fetch 边界替换，不启动服务器、浏览器或真实身份提供方。

## Alternatives considered

把所有输入 String 化能避免部分 trim 错误，却会把对象、数组和数字伪装成授权码或提供方 ID，并仍可能触发对象转换异常。增加整段 catch 可把异常转换为错误响应，但会混淆输入错误与真正的提供方或内部故障。因此验证实际不可信字段，保留后续错误可见性。

## Consequences

仅新增四个由真实失败复现支持的字段类型判断，不新增重试、备用认证方式、成功兜底或共享管理器。正常接口的 body、header、Cookie 和 status 保持；不再让不合法字段成为未捕获服务器错误。活跃笔记中的 SAML 消息自有键和认证刷新会话归属分别持有不同边界，本记录不替代它们；没有同主题 proposed 或 rejected 记录。
