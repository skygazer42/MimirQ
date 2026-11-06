# Agent Note: 流水线偏好读完存储后再持久化

Status: implemented

## Problem

PipelineOptionsProvider 的一个 effect 读取已保存设置，另一个 effect 立即把初始默认 state 写入同一存储键。React 严格模式首次挂载会重新执行 effect：第一次写入的默认值被第二次读取采用，已有 enabled 和 chunk_size 因此丢失。实际 Next 配置启用 reactStrictMode；旧 DOM 用例把严格模式放在 Provider 内部，没有覆盖 Provider 自身的重复挂载效果。

## Decision

Provider 用一个本地 storageLoaded 状态表达首次读取已经结束。读取 effect 先按原 JSON／字段规则恢复设置，再完成该状态；持久化 effect 只在状态更新后的 render 写入。严格模式的两次初始 effect 都不能先写默认值，恢复的值可以正常保存。

首次 render 继续使用同一默认状态，保持原 SSR 与客户端水合快照。空存储和损坏 JSON 按原规则使用默认值，再正常持久化。外部存储事件的读取、key、字段默认值、未知扩展字段、公开 Context 值及导入、导出、更新、重置方法保持。没有新 Context、存储工具或请求管理层。

同类三个偏好／能力 Provider 保留实际状态和资源职责；它们不在初始读取后无条件写入同一默认 state，无需复制这个阶段标志。五个 Worker 保留 Comlink 协议、真实 PDF 资源和 SDK 要求的工厂类；两个类型回归入口保持原形式。

能力 Provider 的 parserBackendAvailable 直接用 normalizeParserBackendName 的结果查原 Map。该生产者把空输入归为 auto，其他返回值保持非空，原本的空键分支不可达。仍可能产生空键的分块策略归一化检查保留，两个 Map 的未知值仍返回 undefined。

## Alternatives considered

通过 useState 懒初始化直接读取 localStorage 可以避开两个 effect 的顺序，但会让客户端首次状态与 SSR 默认快照不同。因此保留原首次 render，在恢复完成后再允许写入。

把读取完成放进 ref 可以减少一个 state，但读取 effect 会在同一轮中先置 ref，随后写入 effect 仍使用该轮旧 state；严格模式也仍可能读到被覆盖的默认值。需要让完成状态与恢复的 state 一起进入后续 render。

把存储写入搬进所有 setState updater，可以去掉持久化 effect，却让状态计算产生副作用，并重复分散到更新、导入、重置和存储事件。因此保留单一写入 effect。

## Consequences

已保存偏好在严格模式下保留，后续真实编辑继续持久化；首次存储写入延后到恢复后的 render。这里的加载阶段只负责初始化顺序，不改变原始输入校验或存储失败政策。

真实 ReactDOM、Provider、存储与归一化函数验证默认挂载、严格模式、后续编辑、空存储及损坏 JSON。相同最终测试在精确 b853 基线上三例通过、一例失败；修复后四例通过，与已有治理工具和父面板共 75 例通过。未模拟 storage 或归一化逻辑，没有启动浏览器或后端服务，未执行 Python 测试。PDF OffscreenCanvas 和真实 Worker 通信只核对源码、SDK 与类型，未进行浏览器运行验收。

历史检索命中[治理工具操作归属](2026-11-04-governance-tool-request-ownership.md)与[治理父面板](2026-11-05-governance-parent-workflow.md)，它们持有业务请求与文件状态，不承担 Provider 初始化，本记录不替代原决定。未发现同一初始化决定或需要归档的记录。
