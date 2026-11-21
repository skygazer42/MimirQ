# Agent Note: 解析公共流程区分输入与已构造结果

Status: implemented

## Problem

BaseAdvancedParser 的同步与异步入口分别维护相同的前置校验和转换流程。直接把整个同步入口搬进线程会同时移动路径校验、惰性实例创建与可用性检查，可能改变资源初始化的线程位置。统计又用布尔判断迭代器，无法接收没有真值语义的有效 iterable；无穷浮点页数抛异常，但同值字符串反而按无效数值变零。侧车别名 URL 把显式端口零当作未提供。

## Decision

基类用两个实际复用的步骤管理前置和重工作：_prepare_parser 保持在调用线程处理路径／实例／可用性，_parse_with_parser 执行已有 SDK 回调和 Document 转换。同步入口直接调用，异步入口只将原重工作交给 to_thread；现有转换 hooks、文档顺序、Metadata、错误与日志位置保持。

统计的 documents 仅区分 None 与有效 Iterable，不测试容器真值；只消费实际 Mapping 元数据。原始计数继续保留 None／无效值为零、bool 转整数、字符串先 float 后 int 的既有协议，无穷值统一由预期数值转换错误处理。TypeError／ValueError／OverflowError 是输入边界，未知对象自己抛的 RuntimeError 等程序故障继续可见。

此转换不复用 utils.scalars：后者将 bool 视为缺失并返回可选结果，和统计计数不同。已有位置 tag、图片计数、负数裁零及原／清理后 Markdown 取最大值的规则保持。诊断只直接消费 PyMuPDF 的必填整数 page_count 和自身构造的计数，预算零／负值、逐页失败及 close 的原策略保持。

侧车 URL 继续按原始候选、容器 hostname 与 localhost 的既定顺序生成，只有显式端口缺省才不输出端口。零端口完整保留，不让另一个端口的服务意外接收回退请求；不更改外部 HTTP 层的认证、超时或重试责任。

## Alternatives considered

让 aparse 直接 to_thread(self.parse) 代码最短，却会移动实例创建和检查，也改变原日志的线程位置。继续复制两套流程能保持位置，但每次转换改动需要同步两处；共享两段实际步骤即可保留既有边界，无需统一 parser context 或新微模块。

统一所有标量转换能减少 helper 数量，却会混淆 bool、缺失值、数字字符串和失败政策。对所有 iterable 使用 or[] 简短，但会调用 SDK 容器不保证的 __bool__，直接迭代才符合声明契约。

## Consequences

公共流程的转换只有一个维护点，已成立的内部结果直接读取；原始 SDK／JSON 多形状、合法空结果和可选旁路仍保留校验。调用方取消仍可见，to_thread 内部工作可能继续到它自己的完成点，没有宣称强制停止解析线程。

差分证据使用原始源码、假路径／PDF／parser、本地 asyncio／线程及原生 LangChain Document 数据模型，核对顺序、结果、异常和关闭。没有读取真实业务文档、运行解析器或连接 SDK 服务；真实解析质量、线程安全及远程回退效果仍需对应环境验证。
