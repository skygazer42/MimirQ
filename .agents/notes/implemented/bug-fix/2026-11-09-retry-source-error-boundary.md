# Agent Note: 文档源与资源读取区分缺失和存储故障

Status: implemented

## Problem

`document_processing_dispatch.resolve_retry_source` 在对象存储 stat 阶段捕获所有异常并抛出文件不存在的 404。连接中断、服务端故障或存储凭据错误因此与真实缺少文档源文件表现相同，运营人员和调用方会被引导去寻找已丢失文件，而不是修复存储依赖。

文档下载与图片资源读取也有相同的宽捕获，底层故障会被分别报告为文件或图片不存在，导致三条入口给出同一误导结果。

## Decision

该边界只把 MinIO SDK 的 `S3Error(code="NoSuchKey")` 转换成既有 `404 / Document file not found`，保留原异常链。其他 S3 错误、网络异常、后端配置及意外代码错误直接传播给已有请求错误入口。

安装版本的 MinIO SDK 在带 object_name 的 HEAD 返回 404 时生成 `NoSuchKey`；S3、OSS、COS 等兼容存储继承同一个 stat 实现。本地文件检查、对象 URI 和租户／数据集／文档引用校验仍在原位置执行，真实路径拒绝的 403、无效引用的 404 和存储关闭的 503 保持。

`document_assets`的文档和图片共用对象响应准备：仅真实NoSuchKey返回各自原有404 detail，其他错误直接传播。缺失对象日志保持原对象名／异常文本的截断预算，认证、成员／文档授权、预览绑定、路径解析和对象名校验先于资源读取；读取成功后的ETag、缓存头、Range与SDK流关闭代码保持。对象非空Range跳过304，本地预览图保留先做ETag的差异。

资源准备经已有run_blocking_in_thread进入worker，在其中创建、使用并关闭独立Session。HTTP层先解析当前账号／workspace和两个header字符串，Request和请求Session不跨worker；重复取消也先等准备worker关闭。Response构造完成后Session结束，SDK对象流在后续消费才打开连接。本地预览stat直接消费os.stat_result字段，失败不再转换成缺省ETag／stat元数据。

## Alternatives considered

- 所有异常都返回 404 可以提供一致的失败文案，但无法区分文件缺失与后端故障，掩盖实际修复方向。
- 新增统一 503 包装可以表达存储不可用，但会把凭据、配置、SDK 或代码错误重新合并，且需要另定错误分类契约；现有错误入口已经能保留真实失败。
- 把整个async入口连同Request和原Session搬进线程可以少写资源准备函数，但会模糊请求与数据库的线程所有权；HTTP层只传身份与header值，worker用with独占Session。裸to_thread虽然更短，却无法满足当前线程桥的取消后等待清理约定，因此沿用已有桥。

## Consequences

真实缺少对象继续返回原 404，其余存储故障现在通过既有服务器错误处理暴露。没有新增重试、存储切换、占位源文件或任务派发；stat 失败始终发生在后续处理调度之前。`NoSuchBucket` 属于存储配置／资源问题，不作为文档对象缺失处理。

文件stat故障更早在准备阶段暴露；不省略元数据再让FileResponse重新stat，合法文件／对象的Range与缓存语义保持。Session不再跨整个响应流保持，SDK连接与实际文件发送仍归原响应迭代器及Starlette；本步不宣称覆盖真实网络断连和所有底层连接关闭故障。

第23项资源API从524行到480行，Ruff／格式／AST3.11／编译通过；109组入口、42组Range、32组disposition离线对照及三个真实线程桥重复取消清理通过，原生OpenAPI除下载说明纠正外保持。原SDK迭代器配内存响应核对正常close／release_conn；DB／路径／stat均使用记录器，FileResponse未实际发送文件，没有执行应用测试、真实SQL、HEAD、HTTP或下载。

最初错误分类批次核对SDK错误生成与S3Error.code声明、MinIOService.stat_object、S3CompatibleObjectStore继承关系及重试的唯一生产调用方。当时的完整模块AST对照只允许SDK错误导入、捕获类型收窄及错误码判断；Ruff／格式、Python3.11 AST／编译和Note门禁通过，未新增或运行Python测试，也未执行存储请求、数据库、重试或任务运行时。

此前资源API的错误分类增量另做全模块AST对照，当时变化限定SDK错误导入和两个stat捕获分类，权限与资源响应语句保持；那次同样未执行真实下载、图片或浏览器运行时。第23项后续的worker与响应准备变更及其验证范围按上文单独记录。
