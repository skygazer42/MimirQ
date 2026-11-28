'use client'

import { useState } from 'react'
import {
  Box,
  Link2,
  Database,
  BarChart3,
  Layers,
  Braces,
  Zap,
  Workflow,
  FileText,
  ClipboardList,
  Search,
  ChevronDown,
} from '@/components/icons'
import { Input } from '@/components/ui/input'
import { assetCategories, getAssets } from './ontology-model'
import { NewOntologyObject } from './ontology-objects'
import type { OntologyController } from './use-ontology-workspace'
import styles from './ontology.module.css'

const icons = {
  object_types: Box,
  relations: Link2,
  bindings: Database,
  metrics: BarChart3,
  rules: Layers,
  functions: Braces,
  actions: Zap,
  action_workflows: Workflow,
  document_metadata: ClipboardList,
  concepts: Layers,
  document_templates: FileText,
}

export function OntologyDirectory({ controller: c }: { controller: OntologyController }) {
  const [query, setQuery] = useState('')
  const needle = query.trim().toLocaleLowerCase()
  return (
    <aside className={styles.directory} aria-label="资产目录">
      <div className={styles.mobileDirectory}>
        <label className={styles.field}>
          资产目录
          <select
            aria-label="切换资产类型"
            value={c.category}
            onChange={(event) => c.chooseAsset(assetCategories.find((item) => item.id === event.target.value)!.id)}
          >
            {assetCategories.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label} · {getAssets(c.definition, item.id).length}
              </option>
            ))}
          </select>
        </label>
        {c.category === 'object_types' && (
          <label className={styles.field}>
            当前对象
            <select value={c.selected} onChange={(event) => c.chooseAsset('object_types', event.target.value)}>
              {!c.objectIds.length && <option value="">尚未定义对象</option>}
              {c.objectIds.map((id) => (
                <option value={id} key={id}>
                  {c.definition.object_types[id].label || id}
                </option>
              ))}
            </select>
          </label>
        )}
        {c.category === 'object_types' && (
          <details>
            <summary>新建业务对象</summary>
            <NewOntologyObject controller={c} />
          </details>
        )}
      </div>
      <div className={styles.directoryHeading}>
        <h2>资产目录</h2>
        <span>
          {assetCategories.reduce((sum, category) => sum + getAssets(c.definition, category.id).length, 0)} 项
        </span>
      </div>
      <div className={styles.directorySearch}>
        <Search aria-hidden="true" />
        <Input
          type="search"
          aria-label="搜索资产名称或标识"
          placeholder="搜索资产名称或标识"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <nav className={styles.categoryList} aria-label="本体资产类型">
        {assetCategories.map((category) => {
          const all = getAssets(c.definition, category.id)
          const filtered = all.filter((item) =>
            [item.id, item.label, item.detail ?? ''].some((value) => value.toLocaleLowerCase().includes(needle)),
          )
          const expanded = c.category === category.id || Boolean(needle)
          const Icon = icons[category.id]
          return (
            <div key={category.id} className={styles.category}>
              <button
                aria-label={category.label}
                aria-expanded={expanded}
                data-current={c.category === category.id}
                data-asset={category.id}
                className={styles.categoryButton}
                onClick={() => c.chooseAsset(category.id)}
              >
                <ChevronDown
                  aria-hidden="true"
                  className={expanded ? styles.expandedChevron : styles.collapsedChevron}
                />
                <span className={styles.iconTray} aria-hidden="true">
                  <Icon />
                </span>
                <span>{category.label}</span>
                <small data-populated={all.length > 0} aria-label={all.length + ' 项'}>
                  {all.length}
                </small>
              </button>
              {expanded && (
                <ul className={styles.assetList}>
                  {filtered.map((asset) => (
                    <li key={asset.id}>
                      <button
                        aria-current={
                          (category.id === 'object_types' ? c.selected === asset.id : c.selectedAsset === asset.id) &&
                          c.category === category.id
                            ? 'true'
                            : undefined
                        }
                        title={asset.label + ' · ' + asset.id}
                        onClick={() => c.chooseAsset(category.id, asset.id)}
                      >
                        <span>{asset.label}</span>
                        <small>{asset.detail || asset.id}</small>
                      </button>
                    </li>
                  ))}
                  {!filtered.length && <li className={styles.directoryEmpty}>{needle ? '无匹配资产' : '尚未配置'}</li>}
                </ul>
              )}
              {category.id === 'object_types' && c.category === 'object_types' && !needle && (
                <NewOntologyObject controller={c} />
              )}
            </div>
          )
        })}
      </nav>
    </aside>
  )
}
