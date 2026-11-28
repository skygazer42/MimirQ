'use client'

import { useState } from 'react'
import type { DatasetReport, DatasetReportPipelineVersion } from '@/lib/report-schema'
import type { CategoryMetricDatum } from '../types'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { Skeleton } from '@/components/ui/skeleton'
import { Link } from '@/i18n/navigation'
import { AlertCircle, CheckCircle2, ChevronRight, Database, FileText, GitBranch, Layers } from '@/components/icons'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import {
  formatGovernanceCount,
  filterReportFindings,
  formatReportText,
  formatReportPercent,
  reportPipelineFilterLabel,
  shortPipelineHash,
} from '../report-format'
import { buildReportOverview, recordedRiskValue, reportStatusRows } from '../report-overview-model'
import { AuditPanel, ReportRecordRows, FindingsTable } from './report-panels'
import styles from '../reports.module.css'

export type ReportsDashboardProps = Readonly<{
  categoryBarData: CategoryMetricDatum[] | undefined
  categoryStatus: 'pending' | 'error' | 'success'
  categoryErrorMessage: string | undefined
  isRefreshingCategories: boolean
  categoryPaused: boolean
  onRetryCategories: () => void
  report: DatasetReport
  connectorRunsIncluded: boolean
  showOnlyIssues: boolean
  onShowOnlyIssuesChange: (value: boolean) => void
  redact: boolean
}>

const sections = [
  ['overview', '报告总览'],
  ['quality', '数据质量'],
  ['audit', '召回审计'],
  ['structure', '结构与风险'],
] as const

function Distribution({
  rows,
  unit = '文档',
}: {
  rows: Array<{ key: string; name: string; value: number }>
  unit?: string
}) {
  const max = rows.reduce((maximum, row) => Math.max(maximum, row.value), 1)
  return rows.length ? (
    <div className={styles.distribution}>
      {rows.map((row) => (
        <div key={row.key}>
          <span title={row.name}>{formatReportText(row.name)}</span>
          <i aria-hidden="true">
            <i style={{ width: `${Math.max(0, (row.value / max) * 100)}%` }} />
          </i>
          <strong>
            {row.value}
            <small>{unit}</small>
          </strong>
        </div>
      ))}
    </div>
  ) : (
    <p className={styles.inlineEmpty}>暂无分布数据</p>
  )
}

function Versions({ rows, compact = false }: { rows: DatasetReportPipelineVersion[]; compact?: boolean }) {
  const visible = compact ? rows.slice(0, 2) : rows
  return visible.length ? (
    <div className={styles.versions}>
      {visible.map((row) => (
        <div key={row.pipeline_hash}>
          <span title={row.pipeline_hash}>
            {row.pipeline_hash === 'unknown' ? '未记录版本' : shortPipelineHash(row.pipeline_hash)}
          </span>
          <strong>{row.documents} 个文档</strong>
        </div>
      ))}
    </div>
  ) : (
    <p className={styles.inlineEmpty}>暂无处理版本记录</p>
  )
}

function isFailedRun(run: DatasetReport['connectors'][number]) {
  return run.status === 'failed' || run.status === 'error'
}

export function ReportsDashboard(props: ReportsDashboardProps) {
  const [section, setSection] = useState('overview')
  const report = props.report
  const overview = buildReportOverview(report)
  const pipelineFilterLabel = reportPipelineFilterLabel(report.pipeline_hash)
  const statusRows = reportStatusRows(report.profile.by_status)
  const statusTotal = statusRows.reduce((sum, row) => sum + row.value, 0)
  const findings = filterReportFindings(report.profile.findings, props.showOnlyIssues)
  const activeFindings = findings.filter((row) => row.count > 0)
  const files = Object.entries(report.profile.by_file_type)
    .map(([name, value]) => ({ key: name, name, value }))
    .sort((a, b) => b.value - a.value)
  const directories = Object.entries(report.profile.by_directory)
    .map(([name, value]) => ({ key: name, name, value }))
    .sort((a, b) => b.value - a.value)
  const failedRuns = report.connectors.filter(isFailedRun)
  const runRows = props.showOnlyIssues ? failedRuns : report.connectors
  let emptyRunsMessage = '当前范围没有运行记录'
  if (!props.connectorRunsIncluded) emptyRunsMessage = '此报告未附带连接器运行记录'
  else if (props.showOnlyIssues && report.connectors.length > 0) emptyRunsMessage = '附带的运行记录中没有异常'
  const datasetName = formatReportText(report.dataset_name)
  const piiRecorded =
    Object.keys(report.compliance.pii_hits_total).length > 0 || Object.keys(report.profile.pii_hits_total).length > 0
  const secretsRecorded =
    Object.keys(report.compliance.secrets_hits_total).length > 0 ||
    Object.keys(report.profile.secrets_hits_total).length > 0
  const rules = (compact = false) => (
    <FindingsTable
      key={JSON.stringify([report.dataset_id, report.pipeline_hash])}
      rows={compact ? activeFindings : findings}
      onlyIssues={props.showOnlyIssues}
      onOnlyIssuesChange={props.onShowOnlyIssuesChange}
      datasetName={datasetName}
      scope={pipelineFilterLabel}
      compact={compact}
      onExpand={() => setSection('quality')}
      runErrors={failedRuns.length}
      onViewRuns={() => setSection('structure')}
    />
  )
  return (
    <div className={styles.reportBody} data-reports-overview>
      <Tabs value={section} onValueChange={setSection} className={styles.tabsRoot}>
        <TabsList aria-label="报告内容" className={styles.tabs}>
          {sections.map(([id, label]) => (
            <TabsTrigger key={id} value={id} className={styles.tab}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="overview" className={styles.tabBody}>
          {report.profile.total_documents === 0 ? (
            <div className={styles.emptyDataset}>
              <FileText />
              <h2>当前报告范围没有文档</h2>
              <p>可切换处理版本，或前往知识库查看当前可见文档。</p>
              <Link href={`/knowledge?dataset=${encodeURIComponent(report.dataset_id)}`}>
                前往知识库
                <ChevronRight />
              </Link>
            </div>
          ) : (
            <div className={styles.overview}>
              <section className={styles.metrics} aria-label="报告摘要">
                <dl>
                  <div data-tone="source">
                    <dt>
                      <span className={styles.iconTray} aria-hidden="true">
                        <FileText />
                      </span>
                      文档总数
                    </dt>
                    <dd>
                      {report.profile.total_documents}
                      <small>{pipelineFilterLabel}</small>
                    </dd>
                  </div>
                  <div data-tone="success">
                    <dt>
                      <span className={styles.iconTray} aria-hidden="true">
                        <CheckCircle2 />
                      </span>
                      已完成
                    </dt>
                    <dd>
                      {overview.completedDocuments}
                      <small>{formatReportPercent(overview.completionPercent)}</small>
                    </dd>
                  </div>
                  <div data-tone="analysis">
                    <dt>
                      <span className={styles.iconTray} aria-hidden="true">
                        <Database />
                      </span>
                      数据体积
                    </dt>
                    <dd>{formatFileSize(report.profile.total_size_bytes)}</dd>
                  </div>
                  <div data-tone="danger">
                    <dt>
                      <span className={styles.iconTray} aria-hidden="true">
                        <AlertCircle />
                      </span>
                      解析失败
                    </dt>
                    <dd>
                      {overview.failedDocuments}
                      <small>{formatReportPercent(overview.failurePercent)}</small>
                    </dd>
                  </div>
                </dl>
              </section>
              <section className={styles.processing}>
                <span>处理结果</span>
                {statusRows.length ? (
                  <>
                    <div className={styles.statusBar} aria-hidden="true">
                      {statusRows.map((row) => (
                        <i
                          key={row.key}
                          className={styles[row.tone]}
                          style={{
                            width: `${(row.value / statusTotal) * 100}%`,
                          }}
                        />
                      ))}
                    </div>
                    <div className={styles.statusLegend}>
                      {statusRows.map((row) => (
                        <span key={row.key} className={cn(styles.semanticPill, styles[row.tone])}>
                          <i className={styles[row.tone]} />
                          {row.label}
                          <strong>{row.value}</strong>
                        </span>
                      ))}
                    </div>
                  </>
                ) : (
                  <span>暂无处理状态统计</span>
                )}
              </section>
              <div className={styles.analysisColumns}>
                <section>
                  <div className={styles.sectionHeading}>
                    <h2>
                      <span className={styles.iconTray} data-tone="source" aria-hidden="true">
                        <Layers />
                      </span>
                      文档分组与来源
                    </h2>
                    <small>记录数 / 当前 {report.profile.total_documents} 个文档</small>
                  </div>
                  <ReportRecordRows rows={overview.documentRecords} />
                </section>
                <AuditPanel report={report} onExpand={() => setSection('audit')} />
              </div>
              {rules(true)}
              <div className={styles.structureSummary}>
                <section>
                  <div className={styles.sectionHeading}>
                    <h2>
                      <span className={styles.iconTray} data-tone="analysis" aria-hidden="true">
                        <GitBranch />
                      </span>
                      处理版本
                    </h2>
                    {report.pipeline_versions.length > 2 && (
                      <button type="button" onClick={() => setSection('structure')}>
                        查看全部 {report.pipeline_versions.length} 个版本
                      </button>
                    )}
                  </div>
                  <Versions rows={report.pipeline_versions} compact />
                </section>
                <section>
                  <div className={styles.sectionHeading}>
                    <h2>
                      <span className={styles.iconTray} data-tone="source" aria-hidden="true">
                        <FileText />
                      </span>
                      文件构成
                    </h2>
                    {files.length > 4 && (
                      <button type="button" onClick={() => setSection('structure')}>
                        查看全部
                      </button>
                    )}
                  </div>
                  <div className={styles.fileTypes}>
                    {files.slice(0, 4).map((row) => (
                      <div key={row.name}>
                        <span>{formatReportText(row.name).toUpperCase()}</span>
                        <strong>{row.value}</strong>
                      </div>
                    ))}
                  </div>
                </section>
              </div>
            </div>
          )}
        </TabsContent>
        <TabsContent value="quality" className={styles.tabBody}>
          <div className={styles.detailPage}>
            {rules()}
            <div className={styles.qualityColumns}>
              <section>
                <div className={styles.sectionHeading}>
                  <h2>文档分组与来源</h2>
                  <small>记录数 / 当前文档数</small>
                </div>
                <ReportRecordRows rows={overview.documentRecords} />
              </section>
              <section>
                <div className={styles.sectionHeading}>
                  <h2>治理元数据记录</h2>
                  <small>记录数 / 各自元数据样本</small>
                </div>
                {overview.governanceRecords.length > 0 ? (
                  <ReportRecordRows rows={overview.governanceRecords} />
                ) : (
                  <p className={styles.inlineEmpty}>尚未取得治理元数据记录</p>
                )}
              </section>
            </div>
            <section className={styles.contentHealth}>
              <div className={styles.sectionHeading}>
                <h2>内容健康</h2>
              </div>
              <dl>
                {[
                  ['URL 变更', formatGovernanceCount(report.governance_audit, 'urls_changed_total')],
                  ['图片处理', formatGovernanceCount(report.governance_audit, 'images_removed_total')],
                  ['隐私信息命中', recordedRiskValue(overview.piiHits, piiRecorded)],
                  ['密钥命中', recordedRiskValue(overview.secretHits, secretsRecorded)],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
              <p className={styles.tableNote}>命中数按持久化记录汇总；缺少检测依据时显示待评估，未记录的处理不计入。</p>
            </section>
            {report.governance_metrics && (
              <section className={styles.governanceDetails}>
                <div className={styles.sectionHeading}>
                  <h2>治理记录</h2>
                  <small>{report.governance_metrics.used_documents} 个已统计文档</small>
                </div>
                <dl>
                  {[
                    ['治理记录', report.governance_metrics.docs_with_governance],
                    ['规则应用次数', report.governance_metrics.rules_applied_total],
                    ['变更文档', report.governance_metrics.changed_documents_total],
                    ['过滤文档', report.governance_metrics.dropped_documents_total],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
                {report.governance_metrics.truncated && <p>统计范围已达到采样上限。</p>}
              </section>
            )}
          </div>
        </TabsContent>
        <TabsContent value="audit" className={styles.tabBody}>
          <div className={styles.detailPage}>
            <AuditPanel report={report} full />
          </div>
        </TabsContent>
        <TabsContent value="structure" className={styles.tabBody}>
          <div className={styles.detailPage}>
            <div className={styles.structureColumns}>
              <section>
                <div className={styles.sectionHeading}>
                  <h2>文件类型分布</h2>
                  <small>文档数量</small>
                </div>
                <Distribution rows={files} />
              </section>
              <section>
                <div className={styles.sectionHeading}>
                  <h2>处理版本</h2>
                  <small>{report.pipeline_versions.length} 个版本</small>
                </div>
                <Versions rows={report.pipeline_versions} />
              </section>
              <section>
                <div className={styles.sectionHeading}>
                  <h2>目录分布</h2>
                  <small>各目录文档数量</small>
                </div>
                <Distribution rows={directories} />
              </section>
              <section>
                <div className={styles.sectionHeading}>
                  <h2>知识分类</h2>
                  <small>
                    当前租户数据集数量
                    {props.categoryPaused
                      ? ' · 等待网络'
                      : props.isRefreshingCategories && props.categoryBarData !== undefined
                        ? ' · 正在更新'
                        : ''}
                  </small>
                </div>
                {props.categoryErrorMessage !== undefined ? (
                  <WorkspaceNotice
                    placement="floating"
                    tone="warning"
                    pending={props.isRefreshingCategories}
                    retry={props.onRetryCategories}
                    retryLabel="重试分类"
                  >
                    {props.categoryErrorMessage}
                    {props.categoryBarData === undefined ? null : '；显示上次读取结果'}
                  </WorkspaceNotice>
                ) : null}
                {props.categoryBarData === undefined ? (
                  props.categoryPaused ? (
                    <p role="status">分类读取已暂停，等待网络恢复。</p>
                  ) : props.categoryStatus === 'pending' ? (
                    <div className={styles.distribution} aria-label="正在读取知识分类" aria-busy="true">
                      {[0, 1, 2].map((index) => (
                        <div key={index}>
                          <Skeleton className="h-4 w-20" />
                          <Skeleton className="h-4 w-full" />
                          <Skeleton className="h-4 w-10" />
                        </div>
                      ))}
                    </div>
                  ) : null
                ) : (
                  <Distribution rows={props.categoryBarData} unit="数据集" />
                )}
              </section>
            </div>
            <section className={styles.connectorSection}>
              <div className={styles.sectionHeading}>
                <h2>运行记录</h2>
                <small>{runRows.length} 条</small>
              </div>
              <div className={styles.localTable}>
                <table className={styles.connectorTable} aria-label="运行记录">
                  <thead>
                    <tr>
                      <th>连接器</th>
                      <th>状态</th>
                      <th>创建时间</th>
                      <th>运行信息</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runRows.map((run) => (
                      <tr key={run.id}>
                        <th scope="row">{run.connector_id}</th>
                        <td>
                          <span
                            className={cn(
                              styles.level,
                              isFailedRun(run) ? styles.error : run.status === 'completed' ? styles.green : styles.info,
                            )}
                          >
                            {isFailedRun(run) ? '失败' : run.status === 'completed' ? '已完成' : run.status}
                          </span>
                        </td>
                        <td>{formatDate(run.created_at)}</td>
                        <td>{formatReportText(run.error_message)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {runRows.length === 0 && <p className={styles.inlineEmpty}>{emptyRunsMessage}</p>}
            </section>
            <details className={styles.rawDetails}>
              <summary>数据来源与范围</summary>
              <pre>
                {JSON.stringify(
                  {
                    dataset: report.dataset_id,
                    pipeline_hash: report.pipeline_hash,
                    generated_at: report.generated_at,
                    data_provenance: report.data_provenance,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
          </div>
        </TabsContent>
      </Tabs>
      <footer className={styles.footer}>
        <span title={datasetName}>
          {datasetName} · {report.profile.total_documents} 个文档
        </span>
        <span>{pipelineFilterLabel}</span>
        <span>HTML／ZIP 脱敏{props.redact ? '已开启' : '已关闭'}</span>
      </footer>
    </div>
  )
}

export function ReportsDashboardSkeleton() {
  return (
    <div className={styles.reportBody} aria-busy="true" aria-label="正在读取报告">
      <p className="sr-only" role="status">
        正在读取报告
      </p>
      <div className={styles.tabs}>
        {[0, 1, 2, 3].map((index) => (
          <Skeleton key={index} className="m-2 h-5 w-20" />
        ))}
      </div>
      <div className={styles.overview}>
        <section className={styles.metrics}>
          <dl>
            {[0, 1, 2, 3].map((index) => (
              <div key={index}>
                <dt>
                  <Skeleton className="h-4 w-20" />
                </dt>
                <dd>
                  <Skeleton className="h-8 w-24" />
                </dd>
              </div>
            ))}
          </dl>
        </section>
        <div className={styles.analysisColumns}>
          {[0, 1].map((index) => (
            <section key={index}>
              <Skeleton className="mb-4 h-5 w-24" />
              {[0, 1, 2, 3, 4].map((row) => (
                <Skeleton key={row} className="my-3 h-5 w-full" />
              ))}
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}
