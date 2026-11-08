# Agent Note: 会话与检索 API 消费实际生产者

Status: implemented

## Problem

会话、检索和证据 API 已有明确的 schema、ORM、SDK 和服务返回值，但部分内部消费者仍重复探测声明字段，把本地计数和固定结果当作未知数据读取。聊天两个入口重复维护同一配额错误，检索 profile 的同一参数映射重复四次，证据套件的空状态计数也有多份字面量。

## Decision

API 直接读取实际声明且由当前调用链产生的字段。会话、消息、反馈、评测和证据对象来自各自 ORM 查询；Pydantic 的显式字段集合由已安装 BaseModel 的属性提供；检查点由当前 LangGraph 工厂编译的图产生，读取其 StateSnapshot 声明成员。可空字段、原始 JSON 的类型检查、值转换和原有错误分支继续留在原来的边界。

聊天流式与普通入口使用已有配额检查函数；profile 的四个调用使用同一份原参数映射，保留每次调用、转换、默认和顺序。套件计数使用一个每次返回新字典的构造器，保持字段及插入顺序。迭代检索结果声明原有固定字段，直接传递已由本地 bool、int、float、len 和字面量产生的值，仍解析实际检索返回的原始数据。

聊天共享配额拦截函数接收实际生产者的 ChatAssistantTokenQuota，直接检查 enabled、exceeded 和 block 模式，不以缺字段默认放行。429 的 limit 直接使用服务已产生的整数；错误字段、文案及两个聊天入口中的调用位置保持。生产者与用量界面的取值归属见[数据集与管线 API](2026-11-05-api-dataset-pipeline-owned-values.md)，源码核对证据位于 E:/MimirQ/.superpowers/quota-usage-readability-20261106/。这项整理不改变服务已有故障放行政策，也不改聊天入口的生成、持久化与流式处理。

内部类型引用实际 ChatRAGConfig、生成问题、RerankResult、LTRFeatureSpec 和回调；LTR 类型只在 TYPE_CHECKING 导入，原有运行时依赖继续按既有时点加载。具有显式 response_model 的 LTR 和相似度端点标注其实际返回类型。Dify 只直接读取已声明 Settings 和实际证据响应字段；配置仍可变，因此数值转换、范围限制、默认及转换异常处理保持。

query-rewrite 的若干字段没有在当前 ChatRAGConfig 声明，继续按原来的可选输入探测。Dify 的动态回调、兼容导出、锁、租约、缓存和实际 HTTP 适配器职责保持。[Dify 纯规则归属](2026-11-04-dify-helper-ownership.md)与[检索编排内部记录](2026-11-05-retrieval-orchestration-owned-values.md)是本轮消费的既有约束，不被替代；历史检索命中的前端会话记录属于其他所有者。

HTML diff 导出直接调用同文件的同步 diff 生产者。该生产者返回普通 Pydantic 响应，没有 awaitable 契约；外层异步路由、原参数、权限、异常、渲染和响应头保持。

## Alternatives considered

把检索执行、Dify 回调和全部请求模型一起迁到新服务能进一步减少路由之间的依赖，但同时涉及现有 HTTP 入口、延迟加载和补丁绑定。本轮保留已确认的入口职责，不通过传入整个模块或新增通用 Context 来迁移。

按数值注解统一删除转换能缩短更多代码，但可变 Settings、请求构造、ORM JSON、provider 结果和数组仍有真实解析职责。只移除实际生产者已确定的重复转换，并保留其余边界。

继续维护重复的配额分支、profile 映射和计数字典可以减少本次 diff，但后续规则修改仍需要同时修改多处；当前使用已有函数或同模块构造器持有同一份规则。

## Consequences

内部字段来源、返回类型和重复规则的归属更清楚。API 的路径、方法、参数与依赖声明、DTO 字段、状态、租户与 ACL、分页排序、事务审计、流式事件及资源寿命继续保持。手工 UUID 校验保留原有 400/404 行为。

直接字段读取依赖当前真实生产者；未来若引入不同对象或扩展 SDK 契约，需要重新核对。验证限于完整源码与调用方审阅、已安装 SDK 源码、Ruff、格式和 Python 3.11 AST；按任务约束不添加、修改或运行 Python 测试，不执行应用、SDK、模型、数据库、服务、网络或其他业务运行时。
