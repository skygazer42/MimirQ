'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { CheckCircle2, AlertCircle } from '@/components/icons'
import { OntologyEdoSource } from '@/components/enterprise-ontology-published'
import type {
  EnterpriseOntologyBindingView as Binding,
  EnterpriseOntologyBindingPreviewView as BindingPreview,
} from '@/types/enterprise-ontology'
import { bindingIssueText, bindingRoles, commaValues } from './ontology-model'
import { OntologyAssetScope } from './ontology-import'
import type { OntologyController } from './use-ontology-workspace'
import styles from './ontology.module.css'

export function OntologyBindings({ controller: c }: { controller: OntologyController }) {
  const update = (index: number, next: Binding) =>
    c.mutate({
      ...c.definition,
      bindings: c.definition.bindings.map((item, current) => (current === index ? next : item)),
    })
  return (
    <fieldset className={styles.formGroup} disabled={Boolean(c.busy) || c.unappliedDefinition}>
      <OntologyAssetScope controller={c} />
      {c.definition.bindings.map((binding, index) => {
        const assets =
          c.assets.data?.filter((asset) => (asset.kind === 'document') === (binding.role === 'document_evidence')) ?? []
        return (
          <section
            key={index}
            className={styles.binding}
            data-selected={c.selectedAsset === String(index)}
            aria-label={'数据绑定 ' + (index + 1)}
          >
            <div className={styles.sectionHeading}>
              <h3>{binding.asset_id || '待选择数据资产'}</h3>
              <span className={styles.semanticBadge} data-role={binding.role}>
                {bindingRoles[binding.role]}
              </span>
            </div>
            <div className={styles.threeFields}>
              <label className={styles.field}>
                对象类型
                <select
                  value={binding.object_type}
                  onChange={(event) =>
                    update(index, { ...binding, object_type: event.target.value, columns: {}, identity_columns: [] })
                  }
                >
                  {c.objectIds.map((id) => (
                    <option key={id}>{id}</option>
                  ))}
                </select>
              </label>
              <label className={styles.field}>
                来源角色
                <select
                  value={binding.role}
                  onChange={(event) => {
                    const role = (Object.keys(bindingRoles) as Binding['role'][]).find(
                      (item) => item === event.target.value,
                    )!
                    update(index, { ...binding, role, columns: {}, identity_columns: [], row_access_column: null })
                  }}
                >
                  {Object.entries(bindingRoles).map(([id, label]) => (
                    <option value={id} key={id}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className={styles.field}>
                资产 ID
                <Input
                  value={binding.asset_id}
                  onChange={(event) => update(index, { ...binding, asset_id: event.target.value })}
                />
              </label>
            </div>
            {assets.length > 0 && (
              <label className={styles.field}>
                选择已登记资产
                <select
                  value={assets.some((item) => item.id === binding.asset_id) ? binding.asset_id : ''}
                  onChange={(event) => update(index, { ...binding, asset_id: event.target.value })}
                >
                  <option value="">选择资产</option>
                  {assets.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {binding.role !== 'document_evidence' && (
              <>
                <label className={styles.field}>
                  物理身份列
                  <Input
                    key={binding.identity_columns.join(', ')}
                    defaultValue={binding.identity_columns.join(', ')}
                    onBlur={(event) => update(index, { ...binding, identity_columns: commaValues(event.target.value) })}
                  />
                </label>
                <div className={styles.twoFields}>
                  {Object.keys(c.definition.object_types[binding.object_type]?.properties ?? {}).map((property) => {
                    const current = binding.columns[property]
                    return (
                      <label className={styles.field} key={property}>
                        {property} 对应源列
                        <Input
                          value={typeof current === 'string' ? current : (current?.column ?? '')}
                          onChange={(event) => {
                            const columns = { ...binding.columns }
                            if (event.target.value)
                              columns[property] =
                                typeof current === 'object'
                                  ? { ...current, column: event.target.value }
                                  : event.target.value
                            else delete columns[property]
                            update(index, { ...binding, columns })
                          }}
                        />
                      </label>
                    )
                  })}
                </div>
              </>
            )}
            {binding.edo_binding && (
              <p className={styles.help}>
                EDO 数据源 · <code>{JSON.stringify(binding.edo_binding)}</code> · 连接与修订可在高级定义中编辑。
              </p>
            )}
            <Button
              variant="ghost"
              className={styles.startAction}
              onClick={() =>
                c.mutate({ ...c.definition, bindings: c.definition.bindings.filter((_, current) => current !== index) })
              }
            >
              移除绑定
            </Button>
          </section>
        )
      })}
      {!c.definition.bindings.length && (
        <p className={styles.help}>还没有数据绑定。为对象选择已登记资产，配置身份列与属性映射。</p>
      )}
      <div className={styles.actions}>
        <Button
          variant="outline"
          disabled={!c.objectIds.length}
          onClick={() =>
            c.mutate({
              ...c.definition,
              bindings: [
                ...c.definition.bindings,
                {
                  object_type: c.selected || c.objectIds[0],
                  role: 'primary',
                  asset_id: '',
                  columns: {},
                  identity_columns: [],
                },
              ],
            })
          }
        >
          添加绑定
        </Button>
        <Button variant="outline" disabled={!c.definition.bindings.length} onClick={c.previewBindings}>
          预检绑定
        </Button>
      </div>
      {c.bindingResults.map((item) => (
        <BindingPreviewResult key={item.object_type + ':' + item.role + ':' + item.asset_id} item={item} />
      ))}
    </fieldset>
  )
}

export function BindingPreviewResult({ item }: { item: BindingPreview }) {
  const properties = [...new Set(item.sample.flatMap(Object.keys))]
  return (
    <section className={styles.previewResult} aria-label={item.asset_id + ' 绑定预览'}>
      <div className={styles.sectionHeading}>
        <h3>
          {item.object_type} · {bindingRoles[item.role]}
        </h3>
        <span className={styles.validationBadge} data-state={item.issues.length ? 'failed' : 'passed'}>
          {item.issues.length ? <AlertCircle aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />}
          {item.issues.length ? item.issues.length + ' 项问题' : '绑定检查通过'}
        </span>
      </div>
      <code className={styles.help}>{item.asset_id}</code>
      <p className={styles.help}>
        {item.identity_columns.length > 0 && (
          <>
            身份列 · {item.identity_columns.join('、')}
            {item.row_count !== null && ' · '}
          </>
        )}
        {item.row_count !== null && <>{item.row_count} 行</>}
        {item.truncated && (
          <>
            {' '}
            · <span>仅显示部分样本</span>
          </>
        )}
      </p>
      {item.edo && <OntologyEdoSource source={item.edo} />}
      {item.issues.length > 0 && (
        <ul className={styles.diagnosticIssues}>
          {item.issues.map((issue) => (
            <li key={issue.code + ':' + issue.field}>{bindingIssueText(issue)}</li>
          ))}
        </ul>
      )}
      {properties.length > 0 && (
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <caption className="sr-only">映射结果样本</caption>
            <thead>
              <tr>
                {properties.map((property) => (
                  <th scope="col" key={property}>
                    {property}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {item.sample.map((row, index) => (
                <tr key={index}>
                  {properties.map((property) => (
                    <td key={property}>
                      {row[property] == null
                        ? '—'
                        : typeof row[property] === 'object'
                          ? JSON.stringify(row[property])
                          : String(row[property])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
