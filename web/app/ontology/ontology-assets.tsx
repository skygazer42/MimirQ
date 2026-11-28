'use client'

import { assetCategories, type AssetCategory } from './ontology-model'
import type { EnterpriseOntologyDefinitionView as Definition } from '@/types/enterprise-ontology'
import type { OpenApiSchema } from '@/types/backend'
import type { OntologyController } from './use-ontology-workspace'
import styles from './ontology.module.css'

function assetRows(
  d: Definition,
  category: AssetCategory,
): { columns: string[]; rows: { id: string; values: string[] }[] } {
  switch (category) {
    case 'metrics':
      return {
        columns: ['指标 / 标识', '对象与聚合', '维度', '单位'],
        rows: Object.entries(d.metrics ?? {}).map(([id, item]) => ({
          id,
          values: [
            item.label || id,
            item.object_type + ' · ' + item.aggregate + '(' + item.property + ')',
            item.dimensions?.join('、') || '未配置',
            item.unit || '—',
          ],
        })),
      }
    case 'rules':
      return {
        columns: ['规则 / 标识', '目标对象', '条件数', '条件'],
        rows: Object.entries(d.rules ?? {}).map(([id, item]) => ({
          id,
          values: [
            item.label || id,
            item.object_type,
            String(item.conditions.length),
            item.conditions.map((condition) => JSON.stringify(condition)).join('；'),
          ],
        })),
      }
    case 'functions':
      return {
        columns: ['函数 / 标识', '依赖指标', '执行器', '返回类型'],
        rows: Object.entries(d.functions ?? {}).map(([id, item]) => ({
          id,
          values: [item.label || id, item.metric, item.executor || 'metric', item.returns || 'number'],
        })),
      }
    case 'actions':
      return {
        columns: ['动作 / 标识', '目标对象与系统', '审批', '参数与前置规则'],
        rows: Object.entries(d.actions ?? {}).map(([id, item]) => ({
          id,
          values: [
            item.label || id,
            item.object_type + ' → ' + item.target,
            item.approval_required ? '需审批' : '预演后执行',
            Object.keys(item.parameters).join('、') +
              (item.preconditions?.length ? ' · 前置规则 ' + item.preconditions.join('、') : '') || '无参数',
          ],
        })),
      }
    case 'action_workflows':
      return {
        columns: ['流程 / 标识', '步骤顺序'],
        rows: Object.entries(d.action_workflows ?? {}).map(([id, item]) => ({
          id,
          values: [
            item.label || id,
            item.actions
              .map((actionId, index) => `${index + 1}. ${d.actions?.[actionId]?.label || actionId}`)
              .join(' → '),
          ],
        })),
      }
    case 'document_metadata':
      return {
        columns: ['元数据 / 标识', '类型', '填写方式', '约束'],
        rows: Object.entries(d.document_metadata ?? {}).map(([id, item]) => ({
          id,
          values: [
            item.label || id,
            item.type,
            item.method === 'manual' ? '从原文补录' : '自动抽取',
            [item.required ? '必填' : '选填', item.multiple ? '多值' : '单值', item.enum?.join('、')]
              .filter(Boolean)
              .join(' · '),
          ],
        })),
      }
    case 'concepts':
      return {
        columns: ['概念 / 标识', '用途', '别名', '来源文档 ID'],
        rows: Object.entries(d.concepts ?? {}).map(([id, value]) => {
          const item = value as OpenApiSchema<'ConceptDefinition'>
          return {
            id,
            values: [item.label, item.description, item.aliases?.join('、') || '—', item.sources.join('、')],
          }
        }),
      }
    case 'document_templates':
      return {
        columns: ['文书模板 / 标识', '字段', '取值来源'],
        rows: Object.entries(d.document_templates ?? {}).map(([id, item]) => ({
          id,
          values: [
            item.title,
            Object.entries(item.fields)
              .map(([fieldId, field]) => (field.label || fieldId) + (field.required ? ' *' : ''))
              .join('、'),
            Object.entries(item.fields)
              .map(([fieldId, field]) => fieldId + ': ' + field.source)
              .join(' · '),
          ],
        })),
      }
    default:
      return { columns: [], rows: [] }
  }
}

export function OntologyAssets({ controller: c }: { controller: OntologyController }) {
  const { columns, rows } = assetRows(c.definition, c.category)
  const label = assetCategories.find((item) => item.id === c.category)!.label
  return (
    <section className={styles.assetDetails} aria-label={label + '定义清单'}>
      <div className={styles.sectionHeading}>
        <h2>{label}</h2>
        <span>{rows.length} 项已定义资产</span>
      </div>
      {rows.length ? (
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th scope="col" key={column}>
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} data-selected={c.selectedAsset === row.id}>
                  {row.values.map((value, index) =>
                    index === 0 ? (
                      <th scope="row" key={index}>
                        {value}
                        <small>
                          <code>{row.id}</code>
                        </small>
                      </th>
                    ) : (
                      <td key={index}>{value}</td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className={styles.help}>尚未定义{label}。在下方完整定义中配置，校验并应用后即可使用。</p>
      )}
    </section>
  )
}
