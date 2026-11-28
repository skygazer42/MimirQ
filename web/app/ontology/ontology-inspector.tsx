'use client'

import { Box, Braces, Zap, CheckCircle2, Circle, ChevronRight } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { assetCategories, bindingCoverage, getAssets, objectLinks } from './ontology-model'
import type { OntologyController } from './use-ontology-workspace'
import styles from './ontology.module.css'

export function OntologyInspector({ controller: c }: { controller: OntologyController }) {
  const links = objectLinks(c.definition, c.selected)
  const coverage = bindingCoverage(c.definition, c.selected)
  const current =
    getAssets(c.definition, c.category).find(
      (item) => item.id === (c.category === 'object_types' ? c.selected : c.selectedAsset),
    ) ?? getAssets(c.definition, c.category)[0]
  const configured = [
    ['数据源', c.definition.bindings.filter((item) => item.object_type === c.selected && item.asset_id.trim()).length],
    ['关系', links.relations.length],
    ['指标', links.metrics.length],
    ['规则', links.rules.length],
    ['函数', links.functions.length],
    ['动作', links.actions.length],
  ] as const
  return (
    <aside className={styles.inspector} aria-label="属性与就绪度检查">
      <h2 className={styles.inspectorHeading}>属性面板</h2>
      <section className={styles.inspectorSection}>
        <div className={styles.objectIdentity} data-asset={c.category}>
          <span className={styles.iconTray} aria-hidden="true">
            <Box />
          </span>
          <strong>{current?.label || '尚未选择资产'}</strong>
          <span>{assetCategories.find((item) => item.id === c.category)!.label}</span>
        </div>
        <dl className={styles.facts}>
          <div>
            <dt>标识</dt>
            <dd>
              <code className={styles.identityCode}>{current?.id ?? '—'}</code>
            </dd>
          </div>
          <div>
            <dt>所属本体</dt>
            <dd>{c.definition.ontology || '未命名本体'}</dd>
          </div>
        </dl>
        {c.category === 'object_types' && c.active && (
          <label className={styles.field}>
            对象显示名
            <Input
              disabled={Boolean(c.busy) || c.unappliedDefinition}
              value={c.active.label ?? ''}
              onChange={(event) =>
                c.mutate({
                  ...c.definition,
                  object_types: {
                    ...c.definition.object_types,
                    [c.selected]: { ...c.active, label: event.target.value || null },
                  },
                })
              }
            />
          </label>
        )}
      </section>
      <section className={styles.inspectorSection} aria-label="关联函数">
        <div className={styles.sectionHeading}>
          <h3>关联函数</h3>
          <span>{links.functions.length}</span>
        </div>
        {links.functions.map(([id, item]) => (
          <button
            key={id}
            className={styles.inspectorLink}
            data-asset="functions"
            onClick={() => c.chooseAsset('functions', id)}
          >
            <span className={styles.iconTray} aria-hidden="true">
              <Braces />
            </span>
            <span className={styles.linkContent}>
              {item.label || id}
              <small>依赖指标 · {item.metric}</small>
            </span>
            <ChevronRight aria-hidden="true" />
          </button>
        ))}
        {!links.functions.length && <p className={styles.help}>暂无关联函数</p>}
      </section>
      <section className={styles.inspectorSection} aria-label="关联动作">
        <div className={styles.sectionHeading}>
          <h3>关联动作</h3>
          <span>{links.actions.length}</span>
        </div>
        {links.actions.map(([id, item]) => (
          <button
            key={id}
            className={styles.inspectorLink}
            data-asset="actions"
            onClick={() => c.chooseAsset('actions', id)}
          >
            <span className={styles.iconTray} aria-hidden="true">
              <Zap />
            </span>
            <span className={styles.linkContent}>
              {item.label || id}
              <small>
                {item.target}
                {item.approval_required && (
                  <>
                    {' '}
                    ·{' '}
                    <span className={styles.semanticBadge} data-approval="true">
                      需审批
                    </span>
                  </>
                )}
              </small>
            </span>
            <ChevronRight aria-hidden="true" />
          </button>
        ))}
        {!links.actions.length && <p className={styles.help}>暂无关联动作</p>}
      </section>
      <section className={styles.inspectorSection} aria-label="建模与绑定就绪度">
        <div className={styles.sectionHeading}>
          <h3>建模与绑定就绪度</h3>
          <strong className={styles.numeric}>{coverage.percent}%</strong>
        </div>
        <progress max={coverage.total || 1} value={coverage.covered} aria-label="属性绑定覆盖率" />
        <p className={styles.help}>
          已映射 {coverage.covered} / {coverage.total} 个属性 · {c.active?.label || c.selected || '未选择对象'}
        </p>
        <ul className={styles.readiness}>
          {configured.map(([label, count]) => (
            <li key={label}>
              {count ? <CheckCircle2 className={styles.ready} aria-hidden="true" /> : <Circle aria-hidden="true" />}
              <span>{label}</span>
              <span className={styles.numeric}>{count ? `${count} 项配置` : '未配置'}</span>
            </li>
          ))}
        </ul>
        <p className={styles.help}>发布前请先运行绑定预检。</p>
      </section>
      <section className={styles.inspectorSection} aria-label="发布状态与版本记录">
        <div className={styles.sectionHeading}>
          <h3>发布状态与版本记录</h3>
          <span>{c.workspace ? '修订 ' + c.workspace.draft_revision : '未保存'}</span>
        </div>
        {c.versions.isFetching && <p className={styles.help}>正在读取发布版本</p>}
        {c.versions.isError && <p className={styles.error}>发布版本读取失败</p>}
        {c.versions.data?.map((item) => (
          <button
            key={item.id}
            className={styles.versionLink}
            onClick={() => {
              c.setVersionId(item.id)
              c.changeStage('runtime')
            }}
          >
            版本 {item.number} · 草稿修订 {item.draft_revision}
            <ChevronRight aria-hidden="true" />
          </button>
        ))}
        {(!c.workspace || (c.versions.isSuccess && !c.versions.data.length)) && (
          <p className={styles.help}>暂无发布版本</p>
        )}
        <Button variant="outline" className={styles.inspectorAction} onClick={() => c.changeStage('runtime')}>
          进入运行应用
        </Button>
      </section>
    </aside>
  )
}
