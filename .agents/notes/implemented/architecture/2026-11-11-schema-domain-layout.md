# Agent Note: API schema 按领域归类

Status: implemented

包形式与域外导入规则由[领域普通包与公共契约](2026-11-11-domain-package-public-api.md)更新；本篇保留最初九域归类及两个实际模型合并的依据。

## Problem

45 个 schema 文件平铺在同一级，账号、文档、统计、评估和系统协议混在一起。同一领域的文件反复使用领域前缀，调用方还要同时导入相邻的小模块；仅统一字段语法不能解决查找模型定义的困难。

## Decision

schema 归入 identity、conversations、documents、datasets、sources、pipelines、evaluation、integrations、system 九个领域目录。base.py 保留共同的 ORM 响应基类。每个文件继续定义实际模型，所有生产调用方指向新定义位置，不保留旧路径文件、兼容别名或全局聚合导出。

数据集健康响应与已有统计摘要合到 datasets/profile.py；证据漂移与修复契约合到 evaluation/references.py。其他模型不为减少文件数强行合并。目录由 45 个 Python 文件收敛为 43 个，所有模型定义、字段、默认值、校验器及配置保留。

领域目录沿用 app/api、app/services 已使用的 Python 命名空间包，不增加空 __init__.py。业务导入仍使用标准显式路径；命名空间目录不执行初始化、不提前加载其他模型。项目目前从源码树运行，若未来改为打包分发，应按实际打包工具确认命名空间包发现配置。

本决定补充[API 路由与输入归属](../simplification/2026-11-10-api-route-and-input-owners.md)和[上传表单模型所有者](../bug-fix/2026-11-11-upload-form-model-ownership.md)的文件位置规则；它们的解析、事务及参数绑定决定保持。

## Alternatives considered

- 保持平铺能够使用较短导入路径，但不能按业务快速定位 45 个混合文件；已有领域命名与调用关系支持归类。
- 将所有模型集中到少数大文件能减少导入行，却会扩大文档和管线文件的职责；只合并两个实际相邻的维护点。
- 在全局或每个领域包入口重导出所有模型能缩短引用，却会隐藏定义位置并扩大加载范围；生产代码直接依赖定义模块。

## Consequences

查找模型先选择领域，再选择实际职责文件。131 个生产导入文件同步迁移；旧 Python 子模块导入路径退出，没有新增适配逻辑。测试文件按用户要求保留原样，其中旧路径引用不据此声明可运行。字段与 HTTP 契约应保持原状，移动类型仍须实际检查框架装配与生成的 OpenAPI。

## Verification

移动前保存当前工作树源码和 OpenAPI。对全部 43 个目标 schema 及 131 个生产调用方比较迁移后的完整非 import AST，核对命名空间目录发现和源文件列表；610 个测试文件的字节哈希保持。共享 HEAD 与暂存区哈希保持。Ruff、格式和 OpenAPI 比较按实际结果记录在维护验证文档中。

Python 测试按用户要求未运行；未启动服务器、处理真实 HTTP 或执行数据库业务。7 个生产调用方的全文件格式检查仍有导入迁移以外的排版差异，未通过扩大格式化来覆盖共享修改。
