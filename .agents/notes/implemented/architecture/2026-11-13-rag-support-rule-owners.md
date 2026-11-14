# Agent Note: RAG支持规则直接依赖实际所有者

Status: implemented

## Problem

components目录的三个文件只声明未被使用的接口和待迁移目录，没有真实pipeline消费者；scheduled反馈wrapper也没有cron／arq注册，仅在普通包再导出。反馈、行业规则和middleware又混入真实生产者之后的重复投影、类型猜测与单用转发。

## Decision

三个无业务根的components脚手架和scheduled纯wrapper退出，真实API Citation模型、手工反馈入口、租户／成员验证及JSONL导出保持。公开facade和框架middleware不因没有直接内部调用就整体删除；只有完整引用图确认无用途且未公开导出的MiddlewareConfig本地DTO退役。

反馈的直接rows与DB路径继续调用同一实际候选构造者，消费其完整summary／候选／规则字段。相同dataset／lineage规则复用既有helper，rating与负例字符串只在实际原始边界处理；dict.get缺省和显式None／falsy的差别保持，不创造实时listener或另一事务所有者。

行业写入口共用现有目录所有者中的必要规则集检查，四处相同错误仍返回原FileNotFoundError。已构造query miner完整字段、Counter及load_ruleset规范化glossary直接消费，纯转发退出；错误、预算、排序、schema、稳定hash及alias顺序保持。YAML安全加载、路径约束、锁、临时文件、权限、flush／fsync、原子替换和canonical／generated优先级完整AST保留。

中间件保真实注册phase／custom顺序／wrapper嵌套、PII兼容对象、class状态和公开链协议。仅固定pattern或实际内部结果之后的重复判断、时钟和单调用preview转发退出。启用PII的失败封闭、Engine既有guard失败开放、取消信号和output先buffer后检查顺序保持，不借风格统一另定策略。

本篇部分更新[既有安全、反馈与行业内部值](../simplification/2026-11-05-policy-feedback-owned-values.md)中重复读取和转发的现状，原始数据／范围／资源与失败原则继续成立。[路由实际生效值](../bug-fix/2026-11-13-routing-effective-values.md)记录相邻但独立的已复现行为修复。

## Alternatives considered

- 保留无根接口以便将来扩展可以避免迁移潜在未知客户，但项目没有实际消费者或注册，不继续维护预建脚手架。
- 将反馈和行业规则再包成Context／manager可以减少参数，却继续隐藏实际所有者，因此直接依赖现有模块函数与真实记录。
- 将全部middleware转为普通函数可以减少类名，但registry／wrapper／有状态生命周期是实际协议，保类并只清理无用途结构。

## Consequences

支持链的依赖和数据主线更直接，真正的外部输入、安全策略和持久化边界保持。旧components接口及scheduled便利名字不提供未知客户兼容壳，历史维护记录保留删除原因，不把退出文件计作现存完成数。

验证覆盖完整源码／定义／调用图、限定AST、stdlib与受控假路径／YAML／锁／时钟／PII／写入端口；不执行真实规则资源、安全扫描、OS锁、YAML或JSONL业务文件操作、模型、网络、数据库或应用测试。有限协议对照不能替代真实安全、并发和持久化回归。
