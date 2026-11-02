# 验证记录

## 干净基线（2026-11-02）

生产代码未修改时运行，提交为 `77b6adc1`。

| 检查 | 真实结果 | 归属 |
| --- | --- | --- |
| Ruff check app tests scripts main.py | 通过 | 原有检查范围 |
| Ruff format --check app tests scripts main.py | 815 个文件需要排版，942 个已符合 | 历史排版差异，含随后排除的上游代码 |
| 扩展为所有自研 Python 的 Ruff check | ci/download_verified_wheels.py 两处 T201 | CLI 有意向终端输出，改为精确文件豁免 |
| pytest -q -n 4 --dist worksteal | 2,994 通过、15 跳过、32 失败、16 收集错误，356.80 秒 | 基线失败见单独清单 |
| 用户认证、SAML 端点、配置快照样板测试 | 17 通过 | 首批切片基线 |
| 前端 ESLint | 通过 | 原有规则的干净基线 |
| TypeScript | 通过 | 干净基线 |
| UI/API checks | 全部通过 | 含严格 API 类型漂移基线 |
| Vitest | 127 个文件、420 个用例全部通过 | 干净基线 |
| 初次 Prettier 检查 | 704 个文件需要排版 | 新选定规则下的历史差异，后续分批处理 |
| 前端生产构建 | 通过，退出 0，bundle budget 通过 | 干净基线；有上级锁文件与 webpack 缓存提示 |

## 批次 1：工具与规则

- Ruff 范围覆盖全部 1,724 个自研 Python 文件；第三方和历史迁移明确排除。
- 原来的 docs 排除项会误伤 scripts/docs 下三个自研工具，已移除该宽泛排除。
- ci/download_verified_wheels.py 的终端输出是命令行契约，T201 只豁免这个文件。
- ESLint 配置加载、配置文件自身 lint 均通过；新增组件声明和 type 偏好规则。
- Prettier 使用根目录唯一配置，锁定 prettier 3.9.10 与 eslint-config-prettier 10.1.8。
- 依赖锁文件仅增加这两个开发依赖的 23 行记录，没有升级现有应用依赖。

## Python 纯排版提交

- 795 个自研文件重新排版，929 个原本符合；第三方和历史迁移未排版。
- 逐一解析全部 1,724 个自研 Python 文件，排版前后完整 AST 的 SHA-256 全部相同，差异为 0。
- Ruff check . 与 Ruff format --check . 均通过，覆盖 1,724 个文件。
- 认证、SAML、配置快照的扩大样板测试：32 通过（9.29 秒）。
- 本提交只更新排版。覆盖清单里的语义审核仍为 pending，后续按业务批次处理。

收集错误涉及缺少 huggingface_hub、trio、llama_index、nltk、pymilvus、torch、tencentcloud 等依赖。
未为本地风格重构启动解析器、模型或完整容器栈。32 个失败还包含平台、既有行为断言和并发用例，
不能统一归因于依赖；后续触及相应领域时逐项核对。

完整原始输出保存在本次执行工作区的 logs/；本目录保存可审阅的结果与用例清单。
