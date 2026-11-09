# Agent Note: 文档重试区分文件缺失与存储故障

Status: implemented

## Problem

`document_processing_dispatch.resolve_retry_source` 在对象存储 stat 阶段捕获所有异常并抛出文件不存在的 404。连接中断、服务端故障或存储凭据错误因此与真实缺少文档源文件表现相同，运营人员和调用方会被引导去寻找已丢失文件，而不是修复存储依赖。

## Decision

该边界只把 MinIO SDK 的 `S3Error(code="NoSuchKey")` 转换成既有 `404 / Document file not found`，保留原异常链。其他 S3 错误、网络异常、后端配置及意外代码错误直接传播给已有请求错误入口。

安装版本的 MinIO SDK 在带 object_name 的 HEAD 返回 404 时生成 `NoSuchKey`；S3、OSS、COS 等兼容存储继承同一个 stat 实现。本地文件检查、对象 URI 和租户／数据集／文档引用校验仍在原位置执行，真实路径拒绝的 403、无效引用的 404 和存储关闭的 503 保持。

## Alternatives considered

- 所有异常都返回 404 可以提供一致的失败文案，但无法区分文件缺失与后端故障，掩盖实际修复方向。
- 新增统一 503 包装可以表达存储不可用，但会把凭据、配置、SDK 或代码错误重新合并，且需要另定错误分类契约；现有错误入口已经能保留真实失败。

## Consequences

真实缺少对象继续返回原 404，其余存储故障现在通过既有服务器错误处理暴露。没有新增重试、存储切换、占位源文件或任务派发；stat 失败始终发生在后续处理调度之前。`NoSuchBucket` 属于存储配置／资源问题，不作为文档对象缺失处理。

验证核对 SDK 错误生成与 S3Error.code 声明、MinIOService.stat_object、S3CompatibleObjectStore 继承关系及重试的唯一生产调用方。完整模块 AST 对照仅允许 SDK 错误导入、捕获类型收窄及错误码判断；Ruff check/format、Python 3.11 AST／编译和 Note 门禁通过。依用户要求未新增或运行 Python 测试，未执行存储请求、数据库、重试或任务运行时。
