# Agent Note: 未注册的 Mathpix 适配器退出

Status: implemented

## Problem

Mathpix 只有一个独立解析模块和两个专属 Settings 字段，没有 parser family、backend alias、公开导出或应用／脚本／前端生产调用。继续整理这份代码容易误判它属于当前可选择解析链；旧覆盖文字中的“已有工厂用途”也与实际注册不符。

## Decision

删除 mathpix_parser.py 和 MATHPIX_APP_ID／MATHPIX_APP_KEY 两个无其他消费者的配置声明。引用核查包括 factory、registry、package lazy export、动态查找、脚本、网页和部署文本。真实可选解析器的注册、别名、配置和接口保持；没有给 Mathpix 新增注册，也不留下旧导入转发。

两个 Settings 字段按同一批退出：配置完整 AST 只减少两个 AnnAssign，其余字段、校验器、默认值及 extra=ignore 规则保持。原生字段集从1277变1275；没有读取或修改用户的实际 .env，旧的无用键仍由已有 ignore 规则处理。

## Alternatives considered

将适配器注册到工厂可以让这些代码变成可选功能，但需要新增选择、认证、远程 API、文档产物及错误语义验证，超出此次清理目标。仅整理同步转发或保留两个密钥字段能减少差异，却仍没有生产使用者，无法解决误导性的维护位置。

保留旧路径可让历史测试继续导入，但用户已排除 Python 测试维护，冻结用例不是生产兼容承诺。

## Consequences

当前 app 少一个无入口模块和两个无用设置，退役不计入新增完成文件。原文、原始 SHA 与额外配置快照保留为验证来源；当前 API OpenAPI 不通过这次删除增加或移除路由。历史直接导入测试保持原字节、未运行，不能报告它们删除后仍可收集通过。

需要正式支持 Mathpix 时，应以真实注册与返回契约作为功能入口，再核远程协议和产物，不恢复一个没有消费者的实现来充当功能支持。
