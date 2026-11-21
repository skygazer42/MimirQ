# Agent Note: 连接器终态和来源设置在真实所有者处生效

Status: implemented

## Problem

连接器提交run终态后才更新保存配置，后续没有commit，Session关闭会丢弃状态。失败会话又可能在rollback前查询或读取expired ORM字段，恢复分支无法标记failed。

MinIO原生presign需要timedelta，适配器传整数；Confluence把摄取成功当作页面仍存在的依据；Jira把合法comments0换成20，source_acl又在context投影中丢失。

## Decision

后续入口权限、完整清单和爬取会话边界见[连接器访问与爬取范围](2026-11-14-connector-access-and-crawl-scope.md)；本篇的终态／可选提交和失败恢复责任继续成立。

run终态先按原事务提交，保存配置在既有可选同步所有者中独立commit。可选配置提交失败不反向抹掉已持久run，保原监控／关闭与异常政策，不把两个提交称为原子事务。

失败恢复先恢复Session，再查询／读取需要的数据；DB专用路径在实际唯一异常入口、所有emit属性读取之前rollback，失败审计仍属于随后状态提交的事务。不能在审计append之后再次rollback把审计丢掉。generic／Jira与DB专用错误文本和事务所有者分别保持，不增加rollbackAlready开关、重试或默认成功。

MinIO用同一受限秒数构造timedelta。Confluence在有效listing身份解析后就记录observed，再尝试摄取；摄取失败仍计failed，但不误判该现存页面已从来源消失，完整listing／分页／软删gate和cursor政策保持。

Jira仅为max_comments_per_issue区分missing／None默认20与合法0，正边界保持。既有dataclass/context和issue投影携带真实source_acl，原group_mappings、tenant group校验、手工覆盖与fallback／provenance规则继续由原所有者处理。

七份完全同体cancelled检查共用现有runtime函数，各真实调用具名依赖；单用成功状态装箱、重复ADF分派和未读取投影退出，不新增状态框架。HTTP／lease／ingestion／tenant／SQL和资源字面值保持。

## Alternatives considered

- 合并终态与可选配置为一个提交可以声称原子，但会让旁路配置失败回滚主run；保持既有两种责任，只补缺失提交。
- 只在mark-failed helper内rollback更集中，却不能保护更早的ORM属性读取；放在实际拥有失败事务的入口。
- 仅因摄取失败删除页面能清理更多旧数据，但“来源存在”与“本次处理成功”不同，使用实际listing身份。

## Consequences

配置终态不再因关闭丢失，正常恢复能记录failed，来源失败不会误删存在的页面，已验证设置能传到真实SDK与ACL所有者。这些是明确行为修复，不能只称排版或保证所有IO故障都恢复成功。

验证使用原控制器AST和受控Session／expired属性／审计append／SDK／listing／ACL端口，保留原失败与修后证据；六类故障、独立可选提交失败及代表性风格路径分别核对。没有真实connector、SQL、MinIO、HTTP、线程或应用测试，不能据此证明真实事务、分页完整性和网络同步通过。
