'use client'

import { BarChart3, Database, FileText, Gauge, TextCursorInput } from '@/components/icons'
import { cn } from '@/lib/utils'
import { Skeleton } from '@/components/ui/skeleton'
import { useMediaQuery } from '@/hooks/use-media-query'
import { formatCount, formatWindow, quotaMode, quotaStatus, quotaValue, type QuotaReading } from './usage-model'
import styles from './usage.module.css'

const quotaIcons = { chat: BarChart3, documents: FileText, storage: Database, embedding: TextCursorInput, qps: Gauge }
type Pending = { chat: boolean; tenant: boolean }

function isQuotaPending(quota: QuotaReading, pending: Pending) {
  return quota.enabled === undefined && (quota.key === 'chat' ? pending.chat : pending.tenant)
}

function QuotaProgress({ quota }: Readonly<{ quota: QuotaReading }>) {
  if (quota.progress === undefined) return null
  return (
    <div
      className={cn(styles.progress, styles[quota.tone])}
      role="progressbar"
      aria-label={`${quota.title}已用比例`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={quota.progress}
      aria-valuetext={`已用 ${formatCount(quota.percentage, 1)}%`}
    >
      <span style={{ width: `${quota.progress}%` }} />
    </div>
  )
}

export function QuotaSummary({ quotas, pending }: Readonly<{ quotas: readonly QuotaReading[]; pending: Pending }>) {
  const desktop = useMediaQuery('(min-width: 1200px)')
  const allDisabled = quotas.length === 5 && quotas.every((quota) => quota.enabled === false)
  const readings = (
    <div
      className={styles.quotaBand}
      tabIndex={desktop ? undefined : 0}
      role="group"
      aria-label={desktop ? '配额概览' : '配额概览，可横向滚动'}
    >
      {quotas.map((quota) => {
        const Icon = quotaIcons[quota.key]
        const busy = isQuotaPending(quota, pending)
        return (
          <section
            key={quota.key}
            aria-label={quota.title}
            className={cn(styles.quotaItem, quota.enabled !== true && styles.inactiveQuota)}
            aria-busy={busy}
          >
            <h2>
              <Icon />
              <span>{quota.title}</span>
            </h2>
            <strong className={cn(styles.quotaValue, quota.enabled !== true && styles.inactiveValue)}>
              {quota.enabled ? (
                <>
                  {quotaValue(quota.used, quota)}
                  <small>{quota.key === 'qps' ? ' 请求/秒 · 突发 ' : ' / '}</small>
                  {quotaValue(quota.limit, quota)}
                </>
              ) : busy ? (
                <Skeleton className="h-6 w-24" />
              ) : (
                quotaStatus(quota)
              )}
            </strong>
            <QuotaProgress quota={quota} />
            <span className={styles.quotaScope}>
              {quota.enabled ? (
                <span className={cn(styles.status, styles[quota.tone])}>
                  <i aria-hidden="true" />
                  {quota.exceeded ? '已达上限' : quota.tone === 'warning' ? '接近上限' : quotaStatus(quota)}
                </span>
              ) : null}
              {quota.key === 'qps' && quota.scopes !== undefined && quota.scopes.length > 0
                ? quota.scopes.join(' / ')
                : quota.scope}
              {quota.percentage === undefined ? null : ` · ${formatCount(quota.percentage, 1)}%`}
              {quota.enabled && quota.mode === 'warn' ? ' · 仅告警' : ''}
            </span>
          </section>
        )
      })}
    </div>
  )
  return (
    <section aria-label="租户配额概览">
      {allDisabled && !desktop ? (
        <details className={styles.quotaDisclosure}>
          <summary>
            配额未启用（5 项）<span>展开明细</span>
          </summary>
          {readings}
        </details>
      ) : (
        readings
      )}
    </section>
  )
}

export function QuotaDetails({ quotas, pending }: Readonly<{ quotas: readonly QuotaReading[]; pending: Pending }>) {
  return (
    <section className={styles.quotaDetails} aria-label="完整配额状态">
      <div className={styles.sectionHeading}>
        <h2>租户资源配额</h2>
        <span>所有数据集共享，独立于窗口累计用量</span>
      </div>
      {quotas.map((quota) => {
        const Icon = quotaIcons[quota.key]
        const busy = isQuotaPending(quota, pending)
        return (
          <section key={quota.key} className={styles.quotaDetail} aria-label={`${quota.title}明细`}>
            <div className={styles.quotaIdentity}>
              <h3>
                <Icon />
                {quota.title}
              </h3>
              <span className={cn(styles.status, styles[quota.tone])}>
                <i />
                {busy ? '读取中' : quotaStatus(quota)}
              </span>
            </div>
            <div className={styles.quotaDetailBody} aria-busy={busy}>
              {quota.enabled ? (
                <>
                  <dl className={styles.quotaReadings}>
                    <div>
                      <dt>{quota.key === 'qps' ? '配置速率' : '已用'}</dt>
                      <dd>
                        {quotaValue(quota.used, quota)}
                        {quota.key === 'qps' ? (
                          <small> 请求 / 秒</small>
                        ) : quota.unit !== 'bytes' ? (
                          <small> {quota.unit}</small>
                        ) : null}
                      </dd>
                    </div>
                    <div>
                      <dt>{quota.key === 'qps' ? '突发请求' : '上限'}</dt>
                      <dd>{quotaValue(quota.limit, quota)}</dd>
                    </div>
                    {quota.key !== 'qps' ? (
                      <div>
                        <dt>剩余</dt>
                        <dd>{quotaValue(quota.remaining, quota)}</dd>
                      </div>
                    ) : null}
                  </dl>
                  <QuotaProgress quota={quota} />
                  <p className={styles.quotaDetailMeta}>
                    {quota.scope}
                    {quota.windowStart !== undefined && quota.windowEnd !== undefined
                      ? ` · ${formatWindow(quota.windowStart, quota.windowEnd)}`
                      : ''}
                    {quota.scopes !== undefined && quota.scopes.length > 0 ? ` · ${quota.scopes.join(' / ')}` : null}
                    {quota.mode !== undefined ? ` · ${quotaMode(quota.mode)}` : null}
                  </p>
                </>
              ) : busy ? (
                <Skeleton className="h-6 w-48" />
              ) : (
                <p className={styles.quotaUnavailable}>
                  {quota.enabled === false ? '此项限制未启用。' : '未取得配额，请在页面上方重试读取。'}
                </p>
              )}
            </div>
          </section>
        )
      })}
    </section>
  )
}
