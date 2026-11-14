# Agent Note: 前端入口直接消费已有输入

Status: implemented

## Problem

应用模板为 Next 提供的必需路径补空字符串，再调用只有自己使用的路径模块。该模块把路径转字符串、补根路径，并尝试删除任意首段来猜语言前缀，重复项目 next-intl 导航层已经承担的职责。

根布局已经取得 getLocale 的当前语言，却继续尝试环境变量兜底。AuthGuard 把元信息中的认证模式转字符串、去空格、变小写；实际后端配置只产生 jwt 或 header。

## Decision

Template 使用项目 i18n/navigation 的 usePathname，在唯一消费位置维护管线页面前缀及完整路径段匹配。退出无其他调用方的 pipeline-route-scope 模块，不再自行猜测 locale。路由范围仍为原六类业务页面，不把所有页面都包进管线 Context。

RootLayout 把 getLocale 的结果直接交给已有文档语言解析。请求头的语言校验继续由该解析负责。nonce 的 null 只在进入可选主题 Prop 时映射为 undefined；这是两个真实接口之间的类型适配，不产生默认 nonce。

AuthGuard 直接比较元信息中的模式；元信息未加载、失败和不认识的模式继续阻断受保护内容。认证事件、登录表单保留、私有子树重建及重定向规则保持。QueryProvider 只明确 ReactNode 的类型导入，不改变查询实例或重试策略。

## Alternatives considered

- 保留独立路径模块可以为其他调用方复用，但当前只有模板一个消费点。项目已有导航模块可以提供规范业务路径，本地前缀判断足够表达剩余职责。
- 保留字符串转换能接受非字符串或非标准大小写，但当前认证模式生产者是受限配置，框架路径和语言也已有明确类型。未知认证模式按原边界阻断，不通过转换猜测其含义。

## Consequences

认证与 Provider 初始化的 17 项相关现有测试通过，当前入口的真实浏览器导航流程通过，均未运行真实后端。Next-intl 4.13.2 的固定源码、四段写法记录及 12 个增量声明位于 .frontend-structure/20261112-full-frontend-guidelines/global-components/。

本记录与[管线偏好初始化](../bug-fix/2026-11-05-pipeline-preference-initialization.md)部分相关：这里只说明 Provider 挂载范围及输入所有者，不替代已有 SSR、严格模式和偏好恢复合同。精准检索活跃笔记未发现同一入口整理决定；其他认证请求归属笔记不持有模板路由政策。
