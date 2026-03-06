# SAML SSO（Skeleton / 方案草案）

本项目当前的企业 SSO 主要路径是 **OIDC（PKCE）+ 后端 JWT 验证**（见 `web/README.md`）。\
部分企业（尤其是传统 IdP / 某些合规场景）仍要求 **SAML 2.0**，因此这里提供一个 **“安全默认关闭”** 的 SAML 集成骨架与落地方案。

> 重要：当前仅提供 **路由骨架 + 元数据占位**，并不包含可用于生产的 SAML 校验与会话签发逻辑。

## 当前状态（已提供）

当 `SAML_ENABLED` 未开启时：
- `/api/saml/metadata` 返回 `404`
- `/api/saml/acs` 返回 `404`

当 `SAML_ENABLED=true` 时：
- `/api/saml/metadata` 返回最小化 SP metadata（不含证书/签名）
- `/api/saml/acs` 返回 `501 saml_not_implemented`

实现位置：
- `web/app/api/saml/metadata/route.ts`
- `web/app/api/saml/acs/route.ts`

## 推荐落地方案（下一步实现方向）

### 1) 选择“谁签发最终会话”

MimirQ 的后端鉴权模式以 **JWT** 为主（`AUTH_MODE=jwt`）。SAML 的核心问题是：SAML Assertion 校验通过后，谁来签发可被后端接受的 token？

推荐方案（更安全、可审计）：
- **Next.js（SAML SP）校验 Assertion** → 调用 **后端受信端点**（仅内网/互信）→ 由后端签发 JWT（或短期 access token）
  - 好处：后端可统一审计、统一 tenant / role 绑定逻辑、减少前端信任面。

备选方案（更轻量，但安全边界更难控）：
- Next.js 校验 Assertion 后直接“构造” JWT（需要把后端签名密钥放在 web 侧，不推荐）。

### 2) 必须做的安全校验清单（SAML 生产必需）

在 `web/app/api/saml/acs/route.ts` 中最终实现时，至少要包括：
- 校验 `SAMLResponse` 的 **XML 签名**（使用 IdP x509 cert）
- 校验 `AudienceRestriction` / `Recipient` / `Destination`
- 校验时间窗口：`NotBefore` / `NotOnOrAfter`（考虑时钟漂移）
- 防重放：`InResponseTo` / `Assertion ID` / `SessionIndex` + 存储去重窗口
- 强制 HTTPS（结合反向代理头部；避免混淆 origin）
- 解析主体标识：
  - `NameID` 或 `email`/`upn` 属性映射到 MimirQ account id
- 可选：groups/roles → tenant groups（建议走 SCIM 或 OIDC groups claim 的同一套“组目录”）

### 3) 配置形态建议（未实现，仅建议）

为支持多 IdP（与 OIDC 的 multi-provider 对齐），建议后续引入：
- `SAML_PROVIDERS_JSON`（server-only）
  - `{ id, name?, idp_sso_url, idp_cert_pem, sp_entity_id?, acs_url? }`
- 在 `/api/saml/metadata` 与 `/api/saml/acs` 中通过 `provider_id` 区分不同 IdP

## 与 SCIM / 组权限的协同

SAML 往往只解决 “登录身份”，而 MimirQ 的企业 ACL（dataset/doc group allowlist）依赖 tenant groups：
- 推荐把 **组同步** 统一走 SCIM（或 OIDC groups claim）落库到 `tenant_groups / tenant_group_members`
- SAML ACS 只负责拿到“用户是谁”，尽量不要承载复杂的组同步逻辑（可选做一次性 bootstrap，但不要当主同步通道）

