'use client'

import { useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronRight, Clock3, FileText, ShieldCheck } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Link } from '@/i18n/navigation'
import type { DatasetReport } from '@/lib/report-schema'
import { cn, formatDate } from '@/lib/utils'
import type { ReportRecordRow, ReportFinding } from '../types'
import {
  findingSeverityLabel,
  formatReportText,
  retrievalAuditFailureText,
  retrievalAuditKgRecommendationText,
  retrievalAuditStatusLabel,
  retrievalAuditTone,
} from '../report-format'
import { reportAuditRows, formatRecordShare } from '../report-overview-model'
import styles from '../reports.module.css'

export function ReportRecordRows({ rows }: Readonly<{ rows: readonly ReportRecordRow[] }>) {
  return (
    <div className={styles.coverageRows}>
      {rows.map((row) => (
        <div key={row.label} className={styles.coverageRow}>
          <span>{row.label}</span>
          <i aria-hidden="true">
            <i
              style={{ width: row.total > 0 ? `${Math.max(0, Math.min(100, (row.count / row.total) * 100))}%` : '0%' }}
            />
          </i>
          <strong>
            {row.count} / {row.total}
          </strong>
          <small>{formatRecordShare(row.count, row.total)}</small>
        </div>
      ))}
    </div>
  )
}

export function AuditPanel({
  report,
  full = false,
  onExpand,
}: Readonly<{
  report: DatasetReport
  full?: boolean
  onExpand?: () => void
}>) {
  const audit = report.retrieval_audit
  const rows = reportAuditRows(audit)
  const visible = full ? rows : rows.slice(0, 5)
  const tone = retrievalAuditTone(audit?.status)
  return (
    <section className={styles.auditPanel} aria-label="召回审计结果">
      <div className={styles.sectionHeading}>
        <h2>
          <span className={styles.iconTray} data-tone="analysis" aria-hidden="true">
            <ShieldCheck />
          </span>
          召回审计
        </h2>
        <span className={cn(styles.stateLabel, styles[tone])}>
          {tone === 'rose' ? <AlertCircle /> : tone === 'green' ? <CheckCircle2 /> : <Clock3 />}
          {retrievalAuditStatusLabel(audit?.status)}
        </span>
        {audit !== null && audit.gates.length > 0 ? <small>{audit.gates.length} 项门禁</small> : null}
      </div>
      {visible.length > 0 ? (
        <div className={styles.localTable}>
          <table className={styles.auditTable} aria-label="召回门禁指标">
            <thead>
              <tr>
                <th scope="col">观测指标</th>
                <th scope="col">当前值</th>
                <th scope="col">所属门禁</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={row.key}>
                  <th scope="row">{row.label}</th>
                  <td>{row.value}</td>
                  <td>
                    <span title={`${row.gate} · ${retrievalAuditStatusLabel(row.status)}`}>
                      {formatReportText(row.gate)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className={styles.auditEmpty}>
          <p>
            {audit === null
              ? '尚未取得召回审计。'
              : audit.gates.length > 0
                ? '当前门禁没有摘要指标。'
                : '当前没有门禁记录。'}
          </p>
          {audit === null || audit.gates.length === 0 ? (
            <Link href={`/evaluations?tab=regression&dataset_id=${encodeURIComponent(report.dataset_id)}`}>
              前往评测
              <ChevronRight />
            </Link>
          ) : null}
        </div>
      )}
      {!full &&
      onExpand !== undefined &&
      audit !== null &&
      (rows.length > 0 || audit.gates.length > 0 || audit.status === 'failed') ? (
        <button type="button" className={styles.quietLink} onClick={onExpand}>
          {rows.length > 5 ? `查看全部 ${rows.length} 项指标` : '查看审计详情'}
          <ChevronRight />
        </button>
      ) : null}
      {full && audit !== null ? (
        <>
          <div className={styles.auditFacts}>
            <div>
              <span>失败归因</span>
              <strong>{retrievalAuditFailureText(audit)}</strong>
            </div>
            <div>
              <span>图谱建议</span>
              <strong>{retrievalAuditKgRecommendationText(audit)}</strong>
            </div>
            <div>
              <span>插件引用</span>
              <strong>
                {audit.plugin_refs.length === 0 ? '未绑定' : audit.plugin_refs.map(formatReportText).join('、')}
              </strong>
            </div>
          </div>
          {audit.gates.map((gate, index) => (
            <details
              key={JSON.stringify([report.dataset_id, report.pipeline_hash, report.generated_at, index])}
              className={styles.gateDetails}
              open={gate.failed_conditions.length > 0}
            >
              <summary>
                <span>{formatReportText(gate.name)}</span>
                <small className={cn(styles.stateLabel, styles[retrievalAuditTone(gate.status)])}>
                  {retrievalAuditStatusLabel(gate.status)}
                </small>
              </summary>
              {gate.failed_conditions.length > 0 ? (
                <ul className={styles.failedConditions}>
                  {gate.failed_conditions.map((condition, index) => (
                    <li key={index}>{formatReportText(condition)}</li>
                  ))}
                </ul>
              ) : null}
              <dl>
                <dt>记录来源</dt>
                <dd>{formatReportText(gate.source)}</dd>
                <dt>生成时间</dt>
                <dd>{gate.generated_at === null ? '未提供' : formatDate(gate.generated_at)}</dd>
              </dl>
              <details className={styles.rawDetails}>
                <summary>原始门禁指标</summary>
                <pre>{JSON.stringify(gate.metrics, null, 2)}</pre>
              </details>
            </details>
          ))}
          {audit.recommended_next_action !== null ? (
            <p className={styles.auditAction}>{formatReportText(audit.recommended_next_action)}</p>
          ) : null}
          {audit.plugin_package_hashes.length > 0 ? (
            <details className={styles.rawDetails}>
              <summary>插件包版本</summary>
              <pre>{audit.plugin_package_hashes.join('\n')}</pre>
            </details>
          ) : null}
        </>
      ) : null}
    </section>
  )
}

type FindingDetails = Readonly<{ finding: ReportFinding; datasetName: string; scope: string; open: boolean }>

export function FindingsTable({
  rows,
  onlyIssues,
  onOnlyIssuesChange,
  datasetName,
  scope,
  compact = false,
  onExpand,
  runErrors,
  onViewRuns,
}: Readonly<{
  rows: readonly ReportFinding[]
  onlyIssues: boolean
  onOnlyIssuesChange: (checked: boolean) => void
  datasetName: string
  scope: string
  compact?: boolean
  onExpand: () => void
  runErrors: number
  onViewRuns: () => void
}>) {
  const [details, setDetails] = useState<FindingDetails | null>(null)
  const trigger = useRef<HTMLButtonElement | null>(null)
  const heading = useRef<HTMLHeadingElement | null>(null)
  const visible = compact ? rows.slice(0, 5) : rows
  const hits = rows.reduce((total, finding) => total + finding.count, 0)
  return (
    <section className={styles.findingsSection}>
      <div className={styles.findingsHeading}>
        <h2 ref={heading} tabIndex={-1}>
          <span className={styles.iconTray} data-tone="warning" aria-hidden="true">
            <AlertCircle />
          </span>
          质量规则命中
        </h2>
        <small>
          {rows.length} 类 · {hits} 次命中
        </small>
        {runErrors > 0 ? (
          <button type="button" className={styles.runWarningLink} onClick={onViewRuns}>
            <AlertCircle />
            {runErrors} 条运行异常
            <ChevronRight />
          </button>
        ) : null}
        <label>
          <Checkbox
            checked={onlyIssues}
            onCheckedChange={(checked) => onOnlyIssuesChange(checked === true)}
            aria-label="只看异常"
          />
          只看异常
        </label>
      </div>
      <div className={styles.localTable}>
        <table className={styles.findingsTable} aria-label="质量规则命中">
          <colgroup>
            <col className={styles.levelColumn} />
            <col className={styles.ruleColumn} />
            <col className={styles.countColumn} />
            <col />
            <col className={styles.actionColumn} />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">级别</th>
              <th scope="col">命中规则</th>
              <th scope="col">数量</th>
              <th scope="col">说明</th>
              <th scope="col">
                <span className="sr-only">操作</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((finding) => (
              <tr key={finding.key}>
                <td>
                  <span className={cn(styles.level, styles[finding.severity])}>
                    {finding.severity === 'info' ? <FileText /> : <AlertCircle />}
                    {findingSeverityLabel(finding.severity)}
                  </span>
                </td>
                <th scope="row">{formatReportText(finding.label)}</th>
                <td className={styles.count}>{finding.count}</td>
                <td className={styles.findingDescription}>{formatReportText(finding.description)}</td>
                <td>
                  <Button
                    variant="ghost"
                    aria-label={`查看${formatReportText(finding.label)} · ${finding.key}`}
                    onClick={(event) => {
                      trigger.current = event.currentTarget
                      setDetails({ finding, datasetName, scope, open: true })
                    }}
                  >
                    <ChevronRight />
                    <span>查看</span>
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {visible.length === 0 ? (
        <div className={styles.inlineEmpty}>{onlyIssues ? '当前报告没有异常规则命中' : '当前报告没有规则命中记录'}</div>
      ) : null}
      {compact && rows.length > 5 ? (
        <button type="button" className={styles.moreRows} onClick={onExpand}>
          查看全部 {rows.length} 类规则
          <ChevronRight />
        </button>
      ) : null}
      {!compact && rows.length > 0 ? <p className={styles.tableNote}>按规则统计，命中数未按文档去重。</p> : null}
      <Dialog
        open={details?.open === true}
        onOpenChange={(open) => {
          if (details !== null) setDetails({ ...details, open })
        }}
      >
        {details !== null ? (
          <DialogContent
            className={styles.findingDialog}
            onCloseAutoFocus={(event) => {
              event.preventDefault()
              if (trigger.current?.isConnected) trigger.current.focus()
              else heading.current?.focus()
            }}
          >
            <DialogHeader>
              <DialogTitle>{formatReportText(details.finding.label)}</DialogTitle>
              <DialogDescription>{formatReportText(details.finding.description)}</DialogDescription>
            </DialogHeader>
            <dl>
              <dt>命中次数</dt>
              <dd>{details.finding.count}</dd>
              <dt>数据集</dt>
              <dd>{details.datasetName}</dd>
              <dt>处理范围</dt>
              <dd>{details.scope}</dd>
              <dt>规则标识</dt>
              <dd>{formatReportText(details.finding.key)}</dd>
            </dl>
            <p>显示打开时的规则记录；同一文档可能命中多条规则。</p>
          </DialogContent>
        ) : null}
      </Dialog>
    </section>
  )
}
