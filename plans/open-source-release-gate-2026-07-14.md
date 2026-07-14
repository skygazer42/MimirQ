# 开源发布 Gate 审查（2026-07-14）——上线前最后一道关

> 日期：2026-07-14 ｜ 触发：用户"准备开源上线，最后一次 review"
> 方法：四路并行扫描（泄密 / 发布卫生·License / 部署默认值 / 上线 blocker）+ 主会话对全部 P0 逐行/逐文件复核。
> **本文件是开源发布的裁决清单，不是优化建议。P0 = 不处理绝不能开源。**

## 结论先行

**当前状态不能直接开源。** 有三类硬阻断，性质是"现状公开即违规/违约/连累下游"，与代码质量无关：
1. **客户数据合规**（1 项，最严重）——常州政务真实交付语料入库且在 git 历史中。
2. **License 合规违规**（3 项）——vendor 了 Apache 代码却挂 MIT、AGPL 依赖当 MIT 宣传。
3. **默认部署零凭证接管**（1 项）——默认档=开发档，clone 即跑 = 任意人成 owner，连累所有下游用户。

**好消息（已独立复核确认）**：凭证泄露 = 0（17 个疑似密钥点全是变量名/占位/测试值）；`.env` 从未进 git 历史；`.gitignore` 覆盖到位。所以没有"密钥已泄漏需紧急吊销"的事故——阻断项都是发布前可处理的，但必须处理。

---

## P0 — 硬阻断（逐条已验证）

### P0-1 常州政务客户真实语料入库（最严重，合规/合同风险，不可逆）
- 证据（已验证）：`plugins/pipelines/changzhou-gov-service-knowledge/` **17 个文件被 git 跟踪**，含 `human_mixed_eval_cases.json`（271KB/100 例）等；实测含 **22 个真实常州 0519 政务座机**、真实政务网域名（`cz.jszwfw.gov.cn`/`gjj.changzhou.gov.cn`/`jtj.changzhou.gov.cn` 等）、真实办事大厅地址、真实事项 ID（`11320402...`）、部门全称。是真实客户交付语料，非合成数据。且已存在于多个历史提交（`6cfdc3a5`/`80de03df`/`7da462ce`）。
- 性质：无公民 PII（无身份证/个人手机，已核），信息本身多为公开政务服务数据；但**未经客户+法务授权公开某政府客户的交付语料**是合同/合规/政治风险，一旦公开不可逆。
- 处置（二选一，且都要清历史）：① 客户与法务书面授权后保留；② 替换为合成脱敏样本。无论哪种，因已在历史中，需 `git filter-repo` 清理该目录历史，公开前是唯一时机。

### P0-2 vendored Apache-2.0 代码 + 顶层 MIT，缺 License 副本与保留声明
- 证据（已验证）：顶层 `LICENSE` 是 MIT（`Copyright (c) 2026 skygazer42`）；但 `app/deepdoc/vision/ocr.py` 等带 `Copyright 2025 The InfiniFlow Authors ... Apache License 2.0` 头（vendored 自 RAGFlow）。全仓**无 Apache-2.0 全文、无 NOTICE**；`app/third_party/integrated_pipeline/common/*.py`（file_utils/constants/token_utils）**版权头被剥除**。
- 违反 Apache-2.0 §4(a)（须附 License 副本）与 §4(b)（须保留声明）。MIT 顶层不能替代子组件义务。
- 处置：`app/deepdoc/` 与 `app/third_party/integrated_pipeline/` 各放 Apache-2.0 全文；顶层加 `NOTICE`/`THIRD_PARTY_NOTICES.md` 声明含 InfiniFlow/RAGFlow(Apache-2.0)；给被剥头文件补回 Apache 头。

### P0-3 PyMuPDF（AGPL-3.0）核心依赖 vs 对外宣称 MIT
- 证据（已验证）：`requirements.txt:51 PyMuPDF==1.27.2.2`（AGPL-3.0/商业双授权）；`app/parsing/parsers/pdf_parser.py:8 import fitz`，全仓 19 个文件 import，是核心非可选依赖；README 高调标 MIT。
- 后果：分发含 PyMuPDF 的组合作品时 AGPL 传染，§13 网络条款要求 SaaS 向用户提供整个作品源码。下游按"MIT 自由商用"部署会踩 AGPL copyleft 陷阱——对维护者和下游都是法律敞口。
- 处置（三选一）：① PyMuPDF 改可选默认关，默认走已有 pypdf(BSD)/pdfplumber(MIT)（推荐）；② 保留则 README/LICENSE 显著声明 AGPL 组合约束；③ 购商业授权。

### P0-5 默认部署 = 零凭证远程完全接管（连累所有下游用户，已逐环验证）
- 利用链（四环全部逐行验证）：`config.py:669` `AUTH_MODE` 默认 `"header"` → `env.py:4-5` `is_production_env()` 只认 `ENV=prod/production`，默认 False 使所有生产守卫失效 → `auth.py:58-65` header 模式下任何非空 `X-User-ID` 头即被认证 → `dataset_service.py:32-47` 非生产下未知 `(tenant,user)` 首次访问自动建号并授 `role="owner"`。
- 暴露面：`.env.example:237 HOST=0.0.0.0` + `docker/docker-compose.yml:159` 发布 `8000:8000` 到 0.0.0.0；README `make init`（逐字复制 .env.example、不 gen secret key）→ `make up`（从不设 ENV，`make up-prod` 只是别名）。
- 后果：任意公网 MimirQ 实例，攻击者发 `X-User-ID: anything` + `X-Tenant-ID: 0000...0000` 即成默认租户 owner——读写删所有数据、读取租户级存储的 LLM API Key、访问 admin（settings/audit/observability）；枚举租户 UUID 可跨租户。**生产加固代码本身扎实（CORS/SSRF/SQL 默认安全已核），但全部 opt-in 于 `ENV=production`，而快速开始不设它。**
- 附带 P0：`main.py:27-36` 用 `warnings.filterwarnings` 主动静音了 "SECRET_KEY not configured" 与 "default MinIO credentials" 两条告警——clone 即跑的运维者连内置提示都看不到。
- 处置（建议全做）：① 默认翻转 `AUTH_MODE=jwt`，或让 header 模式需显式 `ENV=dev` 才启用；② 启动检查：`AUTH_MODE=header` 且绑定非 loopback 时拒绝启动，除非显式 `ALLOW_INSECURE_HEADER_AUTH=1`；③ `.env.example` 默认 `HOST=127.0.0.1`；④ README 快速开始正文显著要求先设 `ENV=production`/`AUTH_MODE=jwt`/`SECRET_KEY`，`make init` 默认 `--gen-secret-key`；⑤ 不静音启动告警。

### P0-4 打包 582MB 第三方模型权重，无 license/归属（待 blocker 路补充确认）
- 证据（卫生路报告，部分验证）：`app/deepdoc/resources/models/` 下 59 个 onnx（LFS），无任何 LICENSE。含 PaddleOCR PP-OCRv4(Apache-2.0，须附 license)、TATR(MIT)、`trocr_seal`/`UVDoc`/`layout`（协议不明）。
- 处置：每模型目录补 model card + LICENSE 并入 NOTICE；协议不明者改构建时下载而非入库。

---

## P1 — 发布前应处理（非法律阻断，但涉自有基础设施暴露/发布完整性）

- **默认部署次级项**（默认值路，已验证 P0-5 附带）：`make up-infra` 把数据存储弱口令发布到 0.0.0.0（Postgres `postgres`/Redis 无认证/MinIO minioadmin，仅 infra 模式，标准 `make up` 不发布）；API 文档 `/docs` 默认全开（`main.py:396`，仅生产关）；`/api/v1/meta` 无鉴权泄露 `auth_mode` 供攻击者指纹识别可利用实例。→ dev compose 端口绑 `127.0.0.1:`；meta 去掉 auth_mode。
- **自有生产基础设施硬编码**（泄密路已验证）：生产 Dify 端点曾被硬编码为默认值（`Makefile:37-51` + 约 8 个脚本如 `scripts/dify_console_login.py:19`）；无配套凭证入库。→ 换占位或无默认 env var。
- **artifacts/ 66 个内部报告被跟踪**（已验证）：虽 `.gitignore:70` 已忽略，但历史遗留仍在跟踪，含内部 benchmark 与 "remote-web" 环境标记。→ `git rm --cached -r artifacts/`。
- **.git 体积膨胀 ~1.4GB**：大量非 LFS 大文件直接进 git（`picture.pdf`/`wordnet.zip`/`punkt.zip`/`*.model`/`sample.pdf 16M` 等）。→ 纳入 LFS 或构建时下载；清历史时一并处理。
- **NOTICE/THIRD_PARTY_NOTICES 缺失**：配合 P0-2/P0-4。
- **CHANGELOG 只有 [Unreleased]**：切 v1.0.0 段 + git tag。

## P2 — 整洁度（可上线后迭代）

- 内网信息散落 docs/plans：具体 RFC1918 主机和本机 `/data/temp*` 路径（公网不可达，非紧急）。
- git 历史元数据包含公司邮箱和内网主机派生邮箱；若要求公开历史完全脱敏，需要统一重写作者邮箱。
- SECURITY.md/CODE_OF_CONDUCT 的维护者 QQ 邮箱（有意公开的联系方式，非泄露；是否换团队邮箱自定）。
- web/docs-site package.json 补 `license` 字段；补通用 issue/PR 模板。
- `.env.prod.example` 历史版本存在但已验证无真实密钥（示例文件），非阻断。

---

## 已复核确认干净（放心区）

- **凭证 = 0**：17 个疑似密钥点全为变量名/占位/测试值（`minioadmin` 本地默认、缓存 token 变量、`sk-1234...` 脱敏测试样本）；`.env.example`(589 键)密钥全空或标准默认；`.github/workflows` 仅测试占位与 `${{ secrets.X }}` 正确引用；无私钥/证书。
- **`.env` 从未进 git 历史**（0 记录）；`.gitignore` 正确覆盖 `.env`/密钥/数据/构建产物。
- **无真实 PII**：0 身份证号、0 真实个人手机（"手机号"匹配全是事项 ID/时间戳子串误报）。
- 顶层 MIT LICENSE 与 README 自洽；README 快速开始链路完整、引用的 docs/images 全存在。

---

## 发布前必办清单（按顺序）

1. **[P0-1]** 决策政务语料去留（授权 or 合成替换）→ 无论哪种都要 `git filter-repo` 清历史。
2. **[P0-2]** 补 Apache-2.0 全文 + NOTICE + 回填被剥版权头。
3. **[P0-3]** 处理 PyMuPDF/AGPL（改可选默认关 推荐 / 或显著声明）。
4. **[P0-4]** 模型权重补 license/归属，协议不明者改下载。
5. **[P1]** 自有部署端点换占位；`git rm --cached artifacts/`；大文件 LFS/下载化；切 v1.0.0 + CHANGELOG。
6. 清历史的操作（P0-1、大文件）合并到一次 filter-repo，公开前执行一次。

> 一句话：**凭证干净、无泄漏事故，但"MIT 声明 vs 实际 Apache/AGPL 义务不符"+"政务客户语料入库"两类合规问题使当前状态不可直接开源。全部可在发布前处理，处理完再公开。**
