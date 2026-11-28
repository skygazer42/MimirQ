'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type {
  EnterpriseOntologyObjectDefinitionView as ObjectType,
  EnterpriseOntologyPropertyInputView as Property,
} from '@/types/enterprise-ontology'
import { commaValues, propertyTypes } from './ontology-model'
import type { OntologyController } from './use-ontology-workspace'
import styles from './ontology.module.css'

export function NewOntologyObject({ controller: c }: { controller: OntologyController }) {
  const [id, setId] = useState('')
  return (
    <fieldset className={styles.newObject} disabled={Boolean(c.busy) || c.unappliedDefinition}>
      <label className={styles.field}>
        新对象标识
        <Input value={id} placeholder="例如 work_order" onChange={(event) => setId(event.target.value)} />
      </label>
      <Button
        variant="outline"
        disabled={!id.trim() || Boolean(c.definition.object_types[id.trim()])}
        onClick={() => {
          const next = id.trim()
          c.mutate({
            ...c.definition,
            object_types: { ...c.definition.object_types, [next]: { key: ['id'], properties: { id: 'string' } } },
          })
          c.chooseAsset('object_types', next)
          setId('')
        }}
      >
        添加对象
      </Button>
    </fieldset>
  )
}

export function OntologyProperties({ controller: c }: { controller: OntologyController }) {
  const [id, setId] = useState('')
  const active = c.active
  function edit(next: ObjectType) {
    c.mutate({ ...c.definition, object_types: { ...c.definition.object_types, [c.selected]: next } })
  }
  return (
    <fieldset className={styles.formGroup} disabled={Boolean(c.busy) || c.unappliedDefinition}>
      <div className={styles.tableScroll}>
        <table className={styles.table + ' ' + styles.propertyTable}>
          <caption className="sr-only">对象属性与业务主键</caption>
          <thead>
            <tr>
              <th scope="col">属性标识</th>
              <th scope="col">类型</th>
              <th scope="col">主键</th>
              <th scope="col">枚举值</th>
              <th scope="col">源列映射</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(active.properties).map(([property, raw]) => {
              const field: Property = typeof raw === 'string' ? { type: raw } : raw
              const mappings = c.definition.bindings
                .filter((item) => item.object_type === c.selected && item.asset_id)
                .flatMap((item) => {
                  const mapping = item.columns[property]
                  const column = typeof mapping === 'string' ? mapping : mapping?.column
                  return column ? [column] : []
                })
              return (
                <tr key={c.selected + ':' + property}>
                  <th scope="row">
                    <code>{property}</code>
                    {field.label && <small>{field.label}</small>}
                  </th>
                  <td>
                    <select
                      aria-label={property + ' 字段类型'}
                      value={field.type}
                      onChange={(event) => {
                        const type = propertyTypes.find((item) => item === event.target.value)!
                        edit({
                          ...active,
                          properties: {
                            ...active.properties,
                            [property]: { ...field, type, enum: type === 'string' ? field.enum : [] },
                          },
                        })
                      }}
                    >
                      {propertyTypes.map((type) => (
                        <option key={type}>{type}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <label className={styles.keyCheck}>
                      <input
                        type="checkbox"
                        aria-label={property + ' 主键'}
                        checked={active.key.includes(property)}
                        onChange={(event) =>
                          edit({
                            ...active,
                            key: event.target.checked
                              ? [...active.key, property]
                              : active.key.filter((key) => key !== property),
                          })
                        }
                      />
                      {active.key.includes(property) && (
                        <span className={styles.keyBadge} aria-hidden="true">
                          主键
                        </span>
                      )}
                    </label>
                  </td>
                  <td>
                    {field.type === 'string' ? (
                      <Input
                        aria-label={property + ' 枚举值'}
                        key={field.enum?.join(', ')}
                        placeholder="—"
                        className={styles.enumInput}
                        defaultValue={field.enum?.join(', ')}
                        onBlur={(event) =>
                          edit({
                            ...active,
                            properties: {
                              ...active.properties,
                              [property]: { ...field, enum: commaValues(event.target.value) },
                            },
                          })
                        }
                      />
                    ) : (
                      <span className={styles.help}>—</span>
                    )}
                  </td>
                  <td>
                    <span className={mappings.length ? styles.mapping : styles.help}>
                      {mappings.length ? [...new Set(mappings)].join('、') : <span aria-label="未映射">—</span>}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className={styles.inlineCreate}>
        <label className={styles.field}>
          新属性标识
          <Input value={id} placeholder="例如 status" onChange={(event) => setId(event.target.value)} />
        </label>
        <Button
          variant="outline"
          disabled={!id.trim() || Boolean(active.properties[id.trim()])}
          onClick={() => {
            edit({ ...active, properties: { ...active.properties, [id.trim()]: 'string' } })
            setId('')
          }}
        >
          添加属性
        </Button>
        <p className={styles.help}>业务主键 · {active.key.length ? active.key.join(' + ') : '尚未选择'}</p>
      </div>
    </fieldset>
  )
}

export function OntologyRelations({
  controller: c,
  objectOnly = false,
}: {
  controller: OntologyController
  objectOnly?: boolean
}) {
  const [id, setId] = useState('')
  const entries = Object.entries(c.definition.relations).filter(
    ([, relation]) => !objectOnly || relation.from === c.selected || relation.to === c.selected,
  )
  return (
    <fieldset className={styles.formGroup} disabled={Boolean(c.busy) || c.unappliedDefinition}>
      <div className={styles.tableScroll}>
        <table className={styles.table}>
          <caption className="sr-only">关联关系定义</caption>
          <thead>
            <tr>
              <th scope="col">关系标识</th>
              <th scope="col">起点</th>
              <th scope="col">终点</th>
              <th scope="col">关系基数</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([relationId, relation]) => (
              <tr key={relationId} data-selected={c.selectedAsset === relationId}>
                <th scope="row">
                  <code>{relationId}</code>
                  {relation.label && <small>{relation.label}</small>}
                </th>
                {(['from', 'to', 'cardinality'] as const).map((field) => (
                  <td key={field}>
                    <select
                      aria-label={relationId + ' ' + (field === 'from' ? '起点' : field === 'to' ? '终点' : '关系基数')}
                      value={relation[field]}
                      onChange={(event) =>
                        c.mutate({
                          ...c.definition,
                          relations: {
                            ...c.definition.relations,
                            [relationId]: { ...relation, [field]: event.target.value },
                          },
                        })
                      }
                    >
                      {(field === 'cardinality'
                        ? ['one_to_one', 'one_to_many', 'many_to_one', 'many_to_many']
                        : c.objectIds
                      ).map((item) => (
                        <option key={item}>{item}</option>
                      ))}
                    </select>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!entries.length && <p className={styles.help}>尚未配置关联关系。</p>}
      <div className={styles.inlineCreate}>
        <label className={styles.field}>
          新关系标识
          <Input value={id} onChange={(event) => setId(event.target.value)} placeholder="例如 order_for_equipment" />
        </label>
        <Button
          variant="outline"
          disabled={!c.objectIds.length || !id.trim() || Boolean(c.definition.relations[id.trim()])}
          onClick={() => {
            c.mutate({
              ...c.definition,
              relations: {
                ...c.definition.relations,
                [id.trim()]: {
                  from: c.selected || c.objectIds[0],
                  to: c.objectIds.at(-1)!,
                  cardinality: 'many_to_one',
                },
              },
            })
            setId('')
          }}
        >
          添加关系
        </Button>
      </div>
    </fieldset>
  )
}
