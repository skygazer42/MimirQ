# Agent Note: 远端探针的真实 helper 与响应边界

Status: implemented

## Problem

部分远端探针用立即调用的 loader 返回一组已有函数和客户端类，使实际所有者与类型被 Any 元组遮住。预检上传另造一个临时响应类，两个解析器探针各自维护同名的百分位算法；若只按表面相似度合并，还容易误改首次使用的依赖缓存、负向权限预期或资源清理时点。

## Decision

六个 loader 在模块启动时只有一次无参数调用，完整函数只导入已有 owner 再按原名返回。脚本在原 bootstrap 之后直接导入相同绑定，退出 loader 与元组装配。预检上传直接构造已有 ApiResponse，保留 status 的原始 requests 转换、body 对象和 elapsed_sec=0.0；唯一消费者仍是原 record_step。

两个 percentile 的完整参数、返回注解和函数体相同。混合后端探针直接使用并发探针中的既有 owner，保留原公式、边界、数值转换和调用位置，不新建通用工具模块。解析器统计中的 len、整数求和及差值直接进入报告；chunking 只消费本地已归一的字典，原始 JSON 数值转换与失败文本保留。KG usefulness 只消费本地 expectation 构造器明确产生的 bool 和 int，列表复制继续保留。

KB permission 的 RuntimeDeps 则承担原有首次使用与 lru_cache 快照合同，现有调用方还使用 build_live_api 注入缝。该记录、缓存、工厂和首次使用的导入时点保留，字段改为实际 LiveApi、ApiResponse 与 Callable 类型；类型引用放在 TYPE_CHECKING。API 参数表达真实客户端类型，原始 body 仍为 Any，不把外部 JSON 当成已验证记录。

全部十九个脚本保留原有 CLI 参数、默认值、输出字段与退出码，包含权限拒绝、禁止词、缓存回退和隔离校验的负向预期。真实 HTTP/requests.Session 客户端、multipart 字节拼装、文件上下文、临时目录、fixture 文本、时钟、线程/进程、超时重试、清理与既有异常策略保持。九个 owner 原文符合约定，完整审查后保持原字节。

## Alternatives considered

统一全部客户端类可以减少请求拼装，但各自的响应形状、截断、错误返回、请求边界与实例状态不同；因此保留实际资源 owner，只在完整合同一致的位置共享。

把 KB permission 也改为启动时导入可以删除更多装配代码，但它会改变已有首次使用缓存与注入缝；因此保留该边界并明确类型。为 percentile 新建模块可以隔离算法，但已有同名 owner 足以承接两个真实消费者，不增加微模块。

## Consequences

真实 helper、响应记录和内部值的归属更直接；首次使用缓存仍有一层转发，代价由原合同承担。以后若需要改变加载时点或对外响应适配，应单独审查相关消费者，不以统一风格为由扩大本批变更。

基线 7e545fa31e4eaa77808c893792aacb7205713c44 的十九个 owner 共 10643 行、364 个函数、8 个类已全文审查。完整模块 AST、CLI/请求/资源源文本合同、签名绑定、哈希、Ruff 和格式检查只提供静态证据；不执行探针、CLI、Python 测试、应用、模型、DB、HTTP、业务 regex、callback 或提取后的业务函数。中央覆盖与独立整合由 Root 维护。
