'use client'

import { Box, Database, Link2, BarChart3, Layers, Workflow, Braces, Zap } from '@/components/icons'
import { bindingRoles, objectLinks, type AssetCategory } from './ontology-model'
import type { OntologyController } from './use-ontology-workspace'
import styles from './ontology.module.css'

export function OntologyLineage({ controller: c }: { controller: OntologyController }) {
  const links = objectLinks(c.definition, c.selected)
  const layers = [
    {
      title: '数据层',
      description: '来源与属性映射',
      icon: Database,
      category: 'bindings',
      nodes: c.definition.bindings.flatMap((item, index) =>
        item.object_type === c.selected
          ? [
              {
                id: String(index),
                label: item.asset_id || '待选择资产',
                detail: bindingRoles[item.role],
                role: item.role,
              },
            ]
          : [],
      ),
    },
    {
      title: '业务对象层',
      description: '身份、主键与属性',
      icon: Box,
      category: 'object_types',
      nodes: [{ id: c.selected, label: c.active.label || c.selected, detail: 'PK · ' + c.active.key.join(' + ') }],
    },
    {
      title: '关系层',
      description: '业务关联与基数',
      icon: Link2,
      category: 'relations',
      nodes: links.relations.map(([id, item]) => ({ id, label: item.label || id, detail: item.cardinality })),
    },
    {
      title: '指标层',
      description: '口径与业务度量',
      icon: BarChart3,
      category: 'metrics',
      nodes: links.metrics.map(([id, item]) => ({ id, label: item.label || id, detail: item.aggregate })),
    },
    {
      title: '规则层',
      description: '条件与业务约束',
      icon: Layers,
      category: 'rules',
      nodes: links.rules.map(([id, item]) => ({
        id,
        label: item.label || id,
        detail: item.conditions.length + ' 个条件',
      })),
    },
    {
      title: '函数与动作层',
      description: '计算、执行与流程',
      icon: Workflow,
      category: 'functions',
      nodes: [
        ...links.functions.map(([id, item]) => ({
          id,
          label: item.label || id,
          detail: '函数',
          category: 'functions',
        })),
        ...links.actions.map(([id, item]) => ({
          id,
          label: item.label || id,
          detail: item.approval_required ? '动作 · 需审批' : '动作',
          approval: item.approval_required,
          category: 'actions',
        })),
        ...links.workflows.map(([id, item]) => ({
          id,
          label: item.label || id,
          detail: '动作流程',
          category: 'action_workflows',
        })),
      ],
    },
  ]
  return (
    <section className={styles.lineage} aria-label="六层语义血缘">
      {layers.map((layer, index) => (
        <div className={styles.lineageRow} data-asset={layer.category} key={layer.title}>
          <div className={styles.layerLabel}>
            <strong>{layer.title}</strong>
            <span>{layer.description}</span>
          </div>
          <div className={styles.layerNodes}>
            {layer.nodes.length ? (
              layer.nodes.map((node) => {
                const category = ('category' in node ? node.category : layer.category) as AssetCategory
                const Icon = category === 'actions' ? Zap : category === 'functions' ? Braces : layer.icon
                return (
                  <button
                    key={category + ':' + node.id}
                    className={styles.lineageNode}
                    data-object={index === 1}
                    data-asset={category}
                    data-role={'role' in node ? node.role : undefined}
                    onClick={() => c.chooseAsset(category, node.id)}
                  >
                    <span className={styles.iconTray} aria-hidden="true">
                      <Icon />
                    </span>
                    <span className={styles.nodeContent}>
                      {node.label}
                      <small className={styles.semanticBadge} data-approval={'approval' in node && node.approval}>
                        {node.detail}
                      </small>
                    </span>
                  </button>
                )
              })
            ) : (
              <button className={styles.unconfigured} onClick={() => c.chooseAsset(layer.category as AssetCategory)}>
                未配置<small>前往配置</small>
              </button>
            )}
          </div>
          {index < layers.length - 1 && <span className={styles.lineageConnector} aria-hidden="true" />}
        </div>
      ))}
    </section>
  )
}
