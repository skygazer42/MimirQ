'use client'

import { BarChart3, Database, FileText, Gauge, TextCursorInput } from '@/components/icons'
import { cn } from '@/lib/utils'
import { formatCount, formatWindow, quotaMode, quotaStatus, quotaValue, type QuotaReading } from './usage-model'
import styles from './usage.module.css'

const quotaIcons = { chat: BarChart3, documents: FileText, storage: Database, embedding: TextCursorInput, qps: Gauge }
type Pending = { chat: boolean; tenant: boolean }

function loading(quota: QuotaReading, pending: Pending) {
  return quota.enabled === null && (quota.key === 'chat' ? pending.chat : pending.tenant)
}

function Progress({ quota }: { quota: QuotaReading }) {
  if (quota.progress === null) return null
  return <div className={cn(styles.progress, styles[quota.tone])} role="progressbar" aria-label={`${quota.title}已用比例`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={quota.progress} aria-valuetext={`已用 ${formatCount(quota.percentage, 1)}%`}><span style={{ width: `${quota.progress}%` }} /></div>
}

export function QuotaSummary({ quotas, pending }: { quotas: QuotaReading[]; pending: Pending }) {
  return <section className={styles.quotaBand} aria-label="租户配额概览">
    {quotas.map(quota => {
      const Icon = quotaIcons[quota.key], busy = loading(quota, pending)
      return <section key={quota.key} aria-label={quota.title} className={styles.quotaItem} aria-busy={busy}>
        <h2><Icon /><span>{quota.title}</span>{quota.exceeded ? <span className={styles.limitState}>已达上限</span> : null}</h2>
        <strong className={cn(quota.enabled !== true && styles.inactiveValue)}>{quota.enabled ? <>{quotaValue(quota.used, quota)}{quota.key === 'qps' ? <small> 请求 / 秒</small> : null}</> : busy ? '读取中…' : quotaStatus(quota)}</strong>
        {quota.enabled ? <span className={styles.quotaLimit}>{quota.key === 'qps' ? `突发 ${quotaValue(quota.limit, quota)}` : `上限 ${quotaValue(quota.limit, quota)}`}</span> : null}
        <Progress quota={quota} />
        <span className={styles.quotaScope}>{quota.key === 'qps' ? quota.scopes.join(' / ') || '速率配置' : quota.scope}{quota.percentage === null ? '' : ` · ${formatCount(quota.percentage, 1)}%`}{quota.enabled && quota.mode === 'warn' ? ' · 仅告警' : ''}</span>
      </section>
    })}
  </section>
}

export function QuotaDetails({ quotas, pending }: { quotas: QuotaReading[]; pending: Pending }) {
  return <section className={styles.quotaDetails} aria-label="完整配额状态">
    <div className={styles.sectionHeading}><h2>租户资源配额</h2><span>所有数据集共享，独立于上方累计用量</span></div>
    {quotas.map(quota => {
      const Icon = quotaIcons[quota.key], busy = loading(quota, pending)
      return <section key={quota.key} className={styles.quotaDetail} aria-label={`${quota.title}明细`}>
        <div className={styles.quotaIdentity}><h3><Icon />{quota.title}</h3><span className={cn(styles.status, styles[quota.tone])}><i />{busy ? '读取中' : quotaStatus(quota)}</span></div>
        <div className={styles.quotaDetailBody}>
          {quota.enabled ? <>
            <dl className={styles.quotaReadings}>
              <div><dt>{quota.key === 'qps' ? '请求速率' : '已用'}</dt><dd>{quotaValue(quota.used, quota)}{quota.key === 'qps' ? <small> 请求 / 秒</small> : quota.unit !== 'bytes' ? <small> {quota.unit}</small> : null}</dd></div>
              <div><dt>{quota.key === 'qps' ? '突发请求' : '上限'}</dt><dd>{quotaValue(quota.limit, quota)}</dd></div>
              {quota.key !== 'qps' ? <div><dt>剩余</dt><dd>{quotaValue(quota.remaining, quota)}</dd></div> : null}
            </dl>
            <Progress quota={quota} />
            <p className={styles.quotaDetailMeta}>{quota.scope}{quota.windowStart && quota.windowEnd ? ` · ${formatWindow(quota.windowStart, quota.windowEnd)}` : ''}{quota.scopes.length ? ` · ${quota.scopes.join(' / ')}` : ''}{quota.mode ? ` · ${quotaMode(quota.mode)}` : ''}</p>
          </> : <p className={styles.quotaUnavailable}>{busy ? '正在读取配额…' : quota.enabled === false ? '此项限制未启用。' : '未取得配额，请在页面上方重试读取。'}</p>}
        </div>
      </section>
    })}
  </section>
}
