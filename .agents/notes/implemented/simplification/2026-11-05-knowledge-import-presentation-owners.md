# Agent Note: 知识库子页面复用实际导入与展示实现

Status: implemented

## Problem

三个导入位置复制了访问成员解析，批量 URL、爬取种子和 sitemap 又复制了只在上限上不同的 URL 解析。这六份副本使格式、数量上限和去重政策容易分开维护。部分组件把较长 Props 写在签名中，API 绑定还经过总入口。短下载步骤与渐变公式也经过复核，但不应为了少量代码让独立页面依赖另一页的 Canvas 或展示实现。

## Decision

纯风格比较固定从行为修复后的 8d48f79bc9a7bb67622b52a4da39ed5b4d0e4b7f 开始。组件保持原有职责与 JSX，只为已有组件定义私有 Props；必要的 DropZone forwardRef 保留。仅作类型使用的导入标为 type，hero 的 mode 使用现有 IngestionMode。

import 特性目录内的 knowledge-import-parsers 持有两种已实际复用的解析：HTTP URL 按调用方显式传入 5、10、50 上限，访问成员保持固定 200 上限。实际消费者是 URL 批量、网页爬取和 Jira payload。两者仍按原分隔、trim、顺序、去重与过滤规则执行。parsePatterns 的换行分隔及独立政策保留在爬取组件中；操作页的 parseLineList／URL 规则不同，也不合并。没有全局解析工具层。

下载继续由现有 document-signals、quarantine-signals 和 report-canvas 各自持有，创建 URL、设置文件名、触发 click 和 revoke 的顺序保持。report-canvas 没有第三方 import 或顶层 DOM／Canvas 初始化，但让 Quarantine 为简单文本下载静态依赖整份 Canvas／JPEG 实现仍增加了无关耦合，因此不抽取这些短步骤。两份渐变公式继续留在原有页面与隔离展示模块，默认空值、精度与颜色字符串保持。

API 直接导入总入口已经重新导出的实际域模块。测试仅为原受控 API 对象增加这些真实模块的 mock 绑定，既有输入、断言和行为用例不变。六份旧解析声明与引用同时退出，没有兼容 facade。其他报告、数据集及已接受工作台中的类似实现属于本类别之外，保持只读。

## Alternatives considered

以一个通用列表解析器接受过滤器、分隔符和默认上限，能进一步压缩行数，但会把成员、URL 与正则模式三种实际政策混在一起；现有两个明确职责已足够表达复用。

三个全局微型 helper 文件可以统一下载、渐变和解析，但前两种抽取制造了无关页面依赖或难追踪的小工具层；因此只有实际减少六份解析维护点的实现进入导入特性目录，下载和渐变保留局部。把解析放入现有 Jira payload 能少一个文件，但另外两种导入不应反向依赖 Jira 的专用生产者。保留旧解析导出再转发可以少改引用，却会留下旧所有者，故迁移本范围真实消费者并删除副本。

## Consequences

共享代码只有原实现和真实调用方需要的参数，没有新增 Hook、状态容器、重试、依赖或产品设置。原始 Number／record／File／配置验证、真实 DTO、文件与配置指纹、HTTP、权限、预算、并发、轮询、DOM、classes、品牌与文案保持。

两个受控路由 fixture 每次 render 先读取局部 search 快照，再把该局部值列入 useMemo 依赖。测试显式 rerender 触发路由变化，当前 URLSearchParams 的稳定性保持；不关闭 exhaustive-deps 或放宽零警告要求。此前两条警告属于本批 fixture，不属于原始基线，原日志与原字节回放保持冻结。

证明比较转译后 AST、JSX、原 API 导出身份、解析限额与 helper 函数体，并运行原受控行为、完整非增量 TypeScript、局部 lint／format 与现有静态 UI／API／笔记门禁。不启动浏览器、服务器、新 UI surface 或真实下载；不据此声称视觉、hydration、网络或后端运行时已验收。

精确检索活跃笔记未命中这些 helper 名称，没有同主题 proposed／rejected 或可完全吸收的决定。[导入访问与会话归属](../bug-fix/2026-11-05-knowledge-ingestion-visit-and-session-ownership.md)负责固定比较基线之前的行为修复，本记录不改变其生命周期决定。
