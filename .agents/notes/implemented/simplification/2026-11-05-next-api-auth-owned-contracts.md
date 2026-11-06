# Agent Note: Next 桥接入口的实际类型与工具归属

Status: implemented

## Problem

SAML 入口各自重复读取环境与 no-store JSON 行为，Markdown 图片入口复制相同的原生响应头读取。认证页和桥接响应另写实际提供方及后端 DTO 已有的字段形状；部分 React、Next 类型又通过值导入或命名空间表达，增加维护点。

## Decision

SAML 复用已存在的 server-auth-route 读取环境、falsey 判断与 JSON 响应，重定向和 XML 专属处理留在对应 route。Markdown 响应头的同一读取规则由现有 response-headers 模块持有，路由直接消费，不增加工具目录或管理器。

认证页直接消费实际 authApi 领域重导出对象和 OidcProviderPublic 字段子集。SAML 只声明实际读取的 SamlExchangeResponse 字段子集，回调错误联合来自已有消息表的键。React 与 Next 类型明确导入，普通组件继续使用 export function，框架要求的默认导出保持。

不把两个权限门合并：开发模式下的 loading 与导航可见性、租户 permission 的判定边界不同。OIDC exchange／refresh 仍分别持有自己的上游协议类型与 Cookie 政策，不新增跨 route 导出或重复兼容层。真实不可信输入与既定失败处理保持。

## Verification

固定中央清单的 25 个原始 owner、2,950 行全文审阅；库函数和页面的唯一凭证写入迁移另记为已接受 owner 的必要引用调整，不重计 owner。两个真实缺陷先以受控 Request／Response 和 React DOM 红绿复现并独立提交；纯风格比较从修复后的固定基线开始，不用归一化隐藏访问或输入验证。

一次性源码证据核对 runtime AST、JSX、实际 API 重导出、私有 helper 的原体及已有共享实现，原测试仅补必要模块 mock 入口，既有用例与断言保持。运行现有类别测试、完整非增量类型检查、局部格式与 lint 和已有静态 UI/API 门禁；没有服务器、浏览器、真实 HTTP、SDK 或 Python 业务执行，也不声称视觉和水合验收。

## Alternatives considered

新增统一 SSO 服务或 route context 可容纳重复规则，但现有工具已持有这些稳定职责，协议间的 Cookie、错误、重定向和 XML 差异仍须保留。把全部入口导向统一状态机或通用响应器会扩大本次兼容面，因此直接使用现有具体所有者。

保持每处局部复制可以避免导入调整，但同一原生头读取和环境规则会继续多处维护。只把完全相同、已有实际共享来源的部分收敛，保留真实策略差异。

## Consequences

维护实际 DTO、提供方字段和公共工具时，入口自动消费其类型或行为，少维护几份相同实现。源码证明需要分别记录共享函数体、引用身份和必要测试适配；它不替代真实环境集成。相邻的 OIDC 输入、登录入口结果归属和既有刷新会话记录持有各自行为边界，本记录只持有行为不变的归属整理；没有同主题 proposed 或 rejected 笔记。
