# Agent Note: API 扫描路径使用统一的仓库相对形式

Status: implemented

## Problem

listFrontendSourceFiles 返回 Node path.relative 的本机路径。Windows 返回反斜杠，而实际 check-api-coverage 调用方用 web/lib/api/ 和 web/lib/api-client.ts 筛选。真实仓库扫描得到的客户端集合为空，parseFrontendRoutes 又把空集合解释为扫描全部前端源码，覆盖检查因此没有使用声明的 API 客户端范围。

## Decision

文件扫描器在返回仓库相对路径时，将本机分隔符转换为正斜杠。实际读取仍通过 path.join 处理该路径；Node 在 Windows 和其他平台都接受这一仓库路径形式。所有消费方因此共享同一份路径约定，不增加独立路径工具或兼容分支。

后端路由、前端调用和 OpenAPI 的解析表达式、扫描目录与扩展名、忽略集合、去重顺序、服务专用路由豁免、严格基线以及现有不可读文件处理保持。生产代理的转发身份清理、CSP、Sentry、构建和包体预算、开发／生产入口及资产同步也保持原文。

## Alternatives considered

在 check-api-coverage 的过滤器里转换路径也能修复这次筛选，但其他消费者和报告仍会收到不同的本机形式。直接在路径生产者统一形式，可以让已有字符串筛选和来源字段遵守同一约定，无须每个调用方重复处理。

把过滤器改为同时匹配两种分隔符可以保留原返回值，但会扩展一个原本明确的内部协议，并把平台分支留给后续调用。统一仓库相对路径即可。

## Consequences

Windows 的 API 覆盖检查使用实际客户端模块，来源路径也与其他平台一致。HTTP 路由和应用运行行为没有变化；依赖扫描输出的外部工具应按仓库路径使用正斜杠。新增回归直接扫描真实源码，再通过实际覆盖筛选与路由提取验证 chat/stream，不模拟文件系统或复制路径转换。

精确旧源码在当前 Windows 环境复现一例失败和一例既有通过；单行修复后，原回归及可信转发身份用例全部通过。检查只执行源码扫描、静态 UI/API 工具、Vitest、TypeScript、ESLint 和 Prettier。额外 OpenAPI 覆盖检查因当前工作区没有生成的 web/openapi.json 而无法完成；没有生成该文件或导入后端应用。没有启动开发／生产服务、浏览器、网络探测、资产同步或 Python 测试。

活跃笔记按 api-contract-lib、FRONTEND_CONTRACT_FILES、正斜杠、backslash 和 POSIX 检索，未发现同一决定；既有 API／手册工具与转发声明的决定保持。
