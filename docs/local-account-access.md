# 本地账号、注册与管理员授权

账号使用密码登录，角色属于工作空间成员。普通注册固定获得 `viewer`，不能在注册请求里指定角色或租户；更高权限由管理员授予。

正式入口为 `/auth`；`/auth?mode=register` 可直接打开注册表单（仍受服务端注册开关控制）。`/brand/explorations/ragvia/login.html` 是独立设计预览，不创建账号；其有效提交会提示用户前往正式入口，不转交填写的凭据。

## 环境配置

```dotenv
AUTH_MODE=jwt
LOCAL_ACCOUNT_REGISTRATION_ENABLED=true
```

`LOCAL_ACCOUNT_REGISTRATION_ENABLED` 默认 `false`，修改后重启 API。关闭开关只关闭新注册，不影响已有账号登录、SSO 或成员权限管理。前端读取 API 的公开认证策略，不需要另外配置注册开关或重新构建前端。

API 首次启动会自动准备管理员，登录页只显示“登录 / 注册”。管理员配置全部留空时，系统会创建默认用户名 `admin`、邮箱 `admin@example.com`，并生成随机密码保存到 `./data/initial-admin.json`。密码不会写入日志或返回前端。

`INITIAL_ADMIN_CREDENTIALS_FILE` 可指定凭据文件位置；默认 Docker Compose 将其保存在 `/data/admin/initial-admin.json`，使用独立的持久卷。文件包含密码，已加入默认 Git 忽略规则。重启不会重置密码；工作空间已有成员时也不会新增默认管理员、覆盖账号或提升角色。

需要指定管理员时，可在首次启动前设置：

```dotenv
INITIAL_ADMIN_EMAIL=admin@example.com
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD_FILE=/path/to/admin-password
```

密码文件只存密码本身；也可改用 `INITIAL_ADMIN_PASSWORD`，二者只能选一个。JWT 签名仍需独立配置 `SECRET_KEY`。初始化只创建首位 owner，不覆盖已有账号、重置密码或自动提升已有用户；成功初始化后可移除初始化凭据。

手动指定管理员时请完整填写身份和密码来源；部分缺失会报配置错误。旧的首位 owner 初始化 API 及生产令牌校验保留兼容，普通登录注册页面不再调用该接口。

## 使用流程

1. 启动 API，系统自动创建默认管理员或 `.env` 指定的管理员；使用相应凭据登录。
2. 开启注册后，普通用户在登录页选择“注册”，填写邮箱、用户名、密码。成功后返回登录表单，预填刚注册的邮箱并提示“注册成功，请登录”。注册不保存会话，用户输入密码登录后再进入产品；首位普通注册用户也保持只读。
3. 新用户是查看者，只能访问已有授权范围内的知识库；注册不授予私有资料的访问权，也不包含编辑或管理权限。
4. 管理员登录后进入“设置 → 成员权限”（`/settings/rbac`），按用户名或邮箱找到成员，选择“编辑者”或“管理员”等角色并保存。
5. 后端每次请求读取当前成员角色，授权变更无需重新签发 JWT；用户切回页面时会重新读取权限，也可在权限提示页点击“重新校验”。至少保留一位管理员，最后一个管理员不能被降级或移除。

本地账号的邮箱由注册者填写，目前不包含邮箱验证或密码找回流程。

## 本机免登录开发

只调试本地功能时，可使用已有的 header 认证模式，无需反复登录。在根目录 `.env` 中设置：

```dotenv
AUTH_MODE=header
NEXT_PUBLIC_USER_ID=<已有管理员的 account_id>
LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED=false
```

同时将 `web/.env.local` 的 `NEXT_PUBLIC_USER_ID` 设为同一个管理员的 `account_id`，`NEXT_PUBLIC_TENANT_ID` 使用该成员所属的工作空间。此模式仍检查数据库中的成员角色；使用已有管理员即可调试管理功能，不会提升普通账号权限。

修改后重启 API 和前端。浏览器已有登录会话时先退出登录，再打开 `/`，侧边栏会显示“开发模式”。前端使用 Next 开发服务器，API 可通过 `uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app` 开启热重载；只需 PostgreSQL、API、前端。

恢复账号登录时，将 `.env` 的 `AUTH_MODE` 改回 `jwt`，两处 `NEXT_PUBLIC_USER_ID` 改回 `demo`，然后重启 API 和前端。免登录模式仅供本机使用，服务保持绑定 `127.0.0.1`；生产环境禁止 header 模式。

## API 契约

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/auth/policy` | 无需登录，返回可用入口、初始化状态、最短密码长度；响应禁止缓存，不返回初始化密钥 |
| `POST /api/v1/auth/signup` | 可配置的普通注册，仅接受邮箱、用户名、密码，固定创建 viewer |
| `POST /api/v1/auth/register` | 兼容原有首位 owner 初始化；已初始化后始终关闭 |
| `POST /api/v1/auth/login` | 现有密码登录 |
| `GET /api/v1/rbac/members` | 管理员查看当前租户成员，包含本地用户名、邮箱；外部身份保留 user_id |
| `PATCH /api/v1/rbac/members/{user_id}` | 管理员修改成员角色 |

登录页加载策略期间或策略请求失败时，已有账号仍可登录；注册入口默认关闭并提供重试。服务端会重新校验开关、租户状态、初始化状态和权限，不信任浏览器缓存的策略。
