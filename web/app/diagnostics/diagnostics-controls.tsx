'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ChevronDown, Loader2, Play } from '@/components/icons'
import { ALL_DATASETS, type DiagnosticsController } from './use-diagnostics'
import type { Metric, Verdict } from './diagnostics-model'
import { cn } from '@/lib/utils'
import styles from './diagnostics.module.css'

export function Status({ label, tone }: Verdict) {
  return (
    <span className={cn(styles.status, styles[tone])}>
      <i aria-hidden="true" />
      {label}
    </span>
  )
}
export function Reading({ metric }: { metric: Metric }) {
  return (
    <span className={cn(styles.reading, metric.raw === null && styles.noReading)}>
      {metric.value}
      {metric.raw !== null && metric.unit ? <small>{metric.unit}</small> : null}
    </span>
  )
}
export function ScopeControls({
  controller: c,
  stacked = false,
}: {
  controller: DiagnosticsController
  stacked?: boolean
}) {
  const [search, setSearch] = useState('')
  if (c.tab === 'performance')
    return (
      <div className={cn(styles.scopeBar, stacked && styles.scopeStack)}>
        <span className={styles.scopeLabel}>检查范围</span>
        <strong>全局 API</strong>
        <span className={styles.scopeHint}>health、ready 与 meta 接口</span>
      </div>
    )

  const searchTerm = search.trim().toLocaleLowerCase()
  const visible = c.documents.filter((document) => document.filename.toLocaleLowerCase().includes(searchTerm))
  return (
    <div className={cn(styles.scopeBar, stacked && styles.scopeStack)}>
      <div className={styles.scopeField}>
        <span>数据集</span>
        <Select
          value={c.scopeSelected && c.datasetId === '' ? ALL_DATASETS : c.datasetId}
          disabled={c.scopeBusy || c.datasetsQuery.isPending}
          onValueChange={c.changeDataset}
        >
          <SelectTrigger aria-label="诊断数据集" className={styles.datasetSelect}>
            <SelectValue placeholder="选择数据集" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_DATASETS}>全部数据集</SelectItem>
            {c.datasets.map((d) => (
              <SelectItem key={d.id} value={d.id}>
                {d.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {c.tab === 'retrieval' ? (
        <div className={styles.scopeField}>
          <span>文档范围</span>
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                disabled={c.preview.status === 'running' || !c.datasetId}
                className={styles.documentSelect}
                aria-label="诊断文档范围"
              >
                <span>{c.documentIds.length ? `已选 ${c.documentIds.length} 个文档` : '全部可检索文档'}</span>
                <ChevronDown />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className={styles.documentPopover}>
              <SearchInput
                aria-label="搜索诊断文档"
                value={search}
                onValueChange={setSearch}
                placeholder="搜索已加载的文档"
              />
              <label className={styles.documentOption}>
                <Checkbox checked={c.documentIds.length === 0} onCheckedChange={() => c.changeDocuments([])} />
                全部可检索文档
              </label>
              <div className={styles.documentOptions}>
                {c.documentsQuery.isPending ? (
                  <p>加载文档中…</p>
                ) : c.documentsQuery.isError ? (
                  <div role="alert">
                    <p>文档目录获取失败。</p>
                    <Button
                      variant="outline"
                      onClick={() => {
                        void c.documentsQuery.refetch()
                      }}
                    >
                      重试
                    </Button>
                  </div>
                ) : visible.length ? (
                  visible.map((d) => (
                    <label className={styles.documentOption} key={d.id} title={d.filename}>
                      <Checkbox
                        checked={c.documentIds.includes(d.id)}
                        onCheckedChange={() =>
                          c.changeDocuments(
                            c.documentIds.includes(d.id)
                              ? c.documentIds.filter((id) => id !== d.id)
                              : [...c.documentIds, d.id],
                          )
                        }
                      />
                      <span>{d.filename}</span>
                    </label>
                  ))
                ) : (
                  <p>没有匹配的文档</p>
                )}
              </div>
              <small>
                {c.documentsQuery.data
                  ? `已加载 ${c.documents.length} / ${c.documentsQuery.data.total} 个文档`
                  : '文档范围未取得'}
              </small>
            </PopoverContent>
          </Popover>
        </div>
      ) : (
        <span className={styles.scopeHint}>当前数据集全部活动分块</span>
      )}
      <span className={styles.scopeCount}>
        {c.datasetId
          ? c.documentsQuery.data
            ? `${c.documentsQuery.data.total} 个文档`
            : ''
          : c.datasetsQuery.data === undefined
            ? null
            : `全部 ${c.datasets.length} 个数据集`}
      </span>
      {c.datasetsQuery.isError ? (
        <span className={styles.fieldError} role="alert">
          数据集获取失败。
          <button
            onClick={() => {
              void c.datasetsQuery.refetch()
            }}
          >
            重试
          </button>
        </span>
      ) : null}
      {c.missingDataset ? (
        <span className={styles.fieldError} role="alert">
          当前数据集已不可用，请重新选择。
        </span>
      ) : null}
      {c.missingDocuments ? (
        <span className={styles.fieldError} role="alert">
          已选文档中有不可用项，请重新选择范围。
        </span>
      ) : null}
      {c.selectedDocumentsUnavailable && c.documentsQuery.isError ? (
        <span className={styles.fieldError} role="alert">
          文档目录获取失败，所选范围已保留。
        </span>
      ) : null}
    </div>
  )
}
export function QueryControl({ controller: c }: { controller: DiagnosticsController }) {
  return (
    <form
      className={styles.queryForm}
      aria-label="检索诊断查询"
      onSubmit={(event) => {
        event.preventDefault()
        void c.runPreview()
      }}
    >
      <label htmlFor="diagnostic-question">查询问题</label>
      <div className={styles.queryInput}>
        <textarea
          id="diagnostic-question"
          aria-label="诊断问题"
          rows={3}
          value={c.query}
          onChange={(event) => c.changeQuery(event.target.value)}
          placeholder="输入要排查的问题"
          disabled={c.preview.status === 'running'}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              event.currentTarget.form?.requestSubmit()
            }
          }}
        />
      </div>
      <div className={styles.queryActions}>
        <Button type="submit" disabled={!c.canRunPreview || c.preview.status === 'running'}>
          {c.preview.status === 'running' ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Play />}
          {c.preview.status === 'running' ? '预览中' : '运行预览'}
        </Button>
        <Button
          type="button"
          variant="outline"
          aria-label="清空查询和结果"
          disabled={!c.query || c.preview.status === 'running'}
          onClick={c.clearPreview}
        >
          清空
        </Button>
      </div>
    </form>
  )
}

export function MetricControls({ controller: c }: { controller: DiagnosticsController }) {
  return (
    <details className={styles.metricControls}>
      <summary>
        显示指标（已选 {c.visibleMetrics.length} / {c.metrics.length} 项）
      </summary>
      <div className={styles.metricChoices}>
        {c.metrics.map((metric) => (
          <label key={metric.key}>
            <Checkbox
              checked={c.visibleMetrics.includes(metric.key)}
              onCheckedChange={() => c.toggleMetric(metric.key)}
            />
            <span>{metric.label}</span>
          </label>
        ))}
      </div>
    </details>
  )
}

export function ServiceDependencies({ controller: c }: { controller: DiagnosticsController }) {
  const readiness = c.ready.isError
    ? '状态未取得'
    : c.ready.data === undefined
      ? '检查中'
      : c.ready.data.ok
        ? '已就绪'
        : '未就绪'
  return (
    <section className={styles.serviceSection} aria-label="服务依赖">
      <div className={styles.sectionHeading}>
        <h2>服务与运行环境</h2>
        <Button variant="ghost" aria-label="查看服务检查详情" onClick={(event) => c.openServices(event.currentTarget)}>
          详情
        </Button>
      </div>
      <dl className={styles.environmentFacts}>
        <div>
          <dt>必需依赖</dt>
          <dd>{readiness}</dd>
        </div>
        <div>
          <dt>向量后端</dt>
          <dd className={styles.backendValue}>{c.vectorBackend ?? '未知'}</dd>
        </div>
        <div>
          <dt>在线评估</dt>
          <dd>
            {c.online.isError ? '未取得' : c.online.isPending ? '检查中' : c.online.data?.enabled ? '已启用' : '未启用'}
          </dd>
        </div>
        <div>
          <dt>{c.services.length} 项服务依赖</dt>
          <dd>
            <Status {...c.systemState} />
          </dd>
        </div>
      </dl>
    </section>
  )
}
