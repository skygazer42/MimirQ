# Agent Note: 切块原文读取与编辑器监听跟随当前文档

Status: implemented

## Problem

原文视图在读取已保存模式前先写入初始 raw，覆盖 editor、rendered 偏好，也让没有偏好的 PDF 失去原有 PDF 默认值。直接访问 localStorage 的写入还会在浏览器拒绝访问时中断整个视图。

自动 File.text effect 把自己设置的 localLoading 放在依赖中，loading render 的 cleanup 使正在等待的读取失效，结果与结束状态都不能发布。手动读取没有相同的文件归属检查，切换文件后完成的旧文本会显示在新文件下。

Monaco 的监听只在 SDK onMount 时安装。React 更新 chunks 或文档选择／滚动 callback 后，旧监听仍使用最初的范围与 callback；共享文档查看器也使用这个组件，可能把新文档操作发给旧文档。

## Decision

模式写入等待读取初始化完成，再调用现有 client-storage 写入所有者。原有模式集合、PDF 回退、保存 key 和界面布局保持，存储不可用仍可阅读文档。

自动与手动读取调用同一个直接异步函数。每次读取持有自己的请求对象，文件／预览文件名变化与卸载使旧对象失效；旧成功、错误和 finally 都不能发布或清除新读取状态。文本结果记录原 File 引用，供当前文件消费。自动读取不会因 loading render 或空结果／失败自动重放，错误仍展示原信息并允许用户手动重试；File.text 本身没有物理取消接口。

Monaco 监听读取一个由 effect 更新的当前 props 引用，沿用原有可选订阅条件、SDK 事件检查和 disposable 清理。范围计算、decorations、滚动恢复、主题、动态加载和 SDK 接口保持原规则，不重建编辑器或增加全局状态。

## Alternatives considered

仅重排模式读写 effect 可以保留普通挂载的部分值，但 StrictMode 的 effect 重放仍会读回第一次写入的 raw，因此使用明确的读取完成状态。合并为 render 阶段直接读取存储虽然更短，却把浏览器操作带进 render，故继续使用原 effect 边界。

只检查 mounted 能阻止卸载后的写入，不能区分同一视图先后选择的两个文件或两次读取。File 与请求对象直接描述实际归属，不新增通用请求 manager。每次 props 变化都重建 Monaco 会造成 SDK 状态与滚动资源重置；更新监听读取的数据即可修复当前消费者。

## Consequences

原文模式与读取状态可以稳定完成，旧文档的文本、选择与滚动结果不会覆盖新文档。现有自动读取大小上限、手动大文件入口、服务器文本优先、错误文案与重试按钮保持；没有增加自动重试、网络请求、存储格式或后台任务。

真实 React DOM 回归在原实现上复现六个原文视图失败，并保留服务器文本与手动失败后重试两个对照；修复后八项通过。独立 Monaco SDK 边界回归复现两个旧范围／callback 失败，事件检查和清理两个对照仍通过；修复后四项通过。只模拟 Context 输入、重型渲染器和 SDK 边界，没有运行浏览器、服务器或 Monaco 实例。

检索没有同模块决定。相邻的[管线偏好初始化](2026-11-05-pipeline-preference-initialization.md)持有公共 PipelineOptionsProvider 的读取后写入规则；本记录应用同样的时序约束于独立原文视图，不修改或吸收该所有者。当前没有同主题 proposed／rejected 记录。
