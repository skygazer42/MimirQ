'use client'

import type { BackendMetaDetails } from '@/lib/api/meta'
import type { SystemStatus } from '@/types/settings'
import { getParserLabel } from '@/lib/parser-options'
import { cn } from '@/lib/utils'
import { CheckCircle2, ChevronDown, XCircle } from '@/components/icons'
import styles from '../settings.module.css'

type SystemStatusSectionProps = { status: SystemStatus; backendMeta: BackendMetaDetails | null }

function StatusRow({
  label,
  ready,
  message,
  configuration = false,
}: Readonly<{ label: string; ready: boolean; message?: string; configuration?: boolean }>) {
  const statusLabel = configuration ? (ready ? '已配置' : '未配置') : ready ? '已连接' : '未连接'
  const detail = message === 'connected' || message === statusLabel ? undefined : message
  return (
    <div className={styles.statusRow}>
      <dt className={styles.statusName}>{label}</dt>
      <dd
        className={cn(
          styles.statusValue,
          ready ? 'text-success' : configuration ? 'text-muted-foreground' : 'text-destructive',
        )}
      >
        {ready ? <CheckCircle2 className="size-4 shrink-0" /> : <XCircle className="size-4 shrink-0" />}
        <span>{statusLabel}</span>
      </dd>
      {detail ? <dd className={styles.statusDetail}>{detail}</dd> : null}
    </div>
  )
}

export function SystemStatusSection({ status, backendMeta }: Readonly<SystemStatusSectionProps>) {
  const parsers = Object.entries(status.parsers)
  const availableParsers = parsers.filter(([, info]) => info.enabled && info.available).length
  return (
    <div className={styles.statusGroups}>
      <section className={styles.statusGroup} aria-labelledby="status-data-title">
        <header className={styles.statusGroupHeader}>
          <h3 id="status-data-title" className={styles.statusGroupTitle}>
            数据服务
          </h3>
          <p className={styles.statusGroupHint}>数据库与向量索引</p>
        </header>
        <dl className={styles.statusItems}>
          <StatusRow label="PostgreSQL" ready={status.database.connected} message={status.database.message} />
          <StatusRow label="向量数据库" ready={status.milvus.connected} message={status.milvus.message} />
        </dl>
      </section>
      <section className={styles.statusGroup} aria-labelledby="status-models-title">
        <header className={styles.statusGroupHeader}>
          <h3 id="status-models-title" className={styles.statusGroupTitle}>
            模型
          </h3>
          <p className={styles.statusGroupHint}>对话与文档向量化</p>
        </header>
        <dl className={styles.statusItems}>
          <StatusRow
            label="语言模型"
            ready={status.llm.configured}
            message={status.llm.configured ? status.llm.model : undefined}
            configuration
          />
          <StatusRow
            label="向量模型"
            ready={status.embedding.configured}
            message={status.embedding.configured ? status.embedding.model : undefined}
            configuration
          />
        </dl>
      </section>
      {backendMeta !== null || parsers.length > 0 ? (
        <details open className={styles.statusParsers}>
          <summary className={cn(styles.statusSummary, 'focus-ring')}>
            <span>解析器与运行环境</span>
            {parsers.length ? (
              <span className={styles.statusParserCount}>
                {availableParsers} / {parsers.length} 可用
              </span>
            ) : null}
            <ChevronDown className={cn(styles.statusChevron, 'size-4 shrink-0 text-muted-foreground')} />
          </summary>
          <div className={styles.statusParserBody}>
            {parsers.length ? (
              <ul aria-label="解析器状态" className={styles.statusParserList}>
                {parsers.map(([key, info]) => {
                  const isAvailable = info.enabled && info.available
                  return (
                    <li key={key} title={info.message} className={styles.statusParserRow}>
                      <span>{key === 'libreoffice' ? 'LibreOffice' : getParserLabel(key)}</span>
                      <span
                        className={cn(styles.statusParserState, isAvailable ? 'text-success' : 'text-muted-foreground')}
                      >
                        {isAvailable ? '可用' : info.enabled ? '不可用' : '未启用'}
                      </span>
                    </li>
                  )
                })}
              </ul>
            ) : null}
            {backendMeta ? (
              <dl aria-label="运行环境" className={styles.statusEnvironment}>
                <div>
                  <dt>API 版本</dt>
                  <dd>{backendMeta.api_version}</dd>
                </div>
                {backendMeta.runtime?.python ? (
                  <div>
                    <dt>Python</dt>
                    <dd>{backendMeta.runtime.python}</dd>
                  </div>
                ) : null}
                {backendMeta.build?.sha ? (
                  <div>
                    <dt>构建版本</dt>
                    <dd title={backendMeta.build.sha}>{backendMeta.build.sha.slice(0, 7)}</dd>
                  </div>
                ) : null}
              </dl>
            ) : null}
          </div>
        </details>
      ) : null}
    </div>
  )
}
