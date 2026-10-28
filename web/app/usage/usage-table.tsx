'use client'

import { ArrowUpRight, ChevronLeft, ChevronRight, Database, Loader2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Link } from '@/i18n/navigation'
import { cn } from '@/lib/utils'
import { averageRetrievalMs, formatCount, formatDuration, shortDatasetId, type UsageRow } from './usage-model'
import { COST_ATTRIBUTION_PAGE_SIZE, paginateUsageRows } from './usage-pagination'
import styles from './usage.module.css'

type Props = {
  rows: UsageRow[]
  mode: 'attribution' | 'resources'
  page: number
  onPageChange: (page: number) => void
  pending: boolean
  failed: boolean
  windowDays: number
}

export function UsageTable({ rows, mode, page, onPageChange, pending, failed, windowDays }: Props) {
  const { items, page: currentPage, pageCount } = paginateUsageRows(rows, page)
  const resourceMode = mode === 'resources'
  if (!rows.length) return <section className={styles.empty} aria-label={resourceMode ? '链路资源状态' : '用量归因状态'} aria-busy={pending}>
    {pending ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Database />}
    <h2>{pending ? '正在读取用量…' : failed ? '未取得完整用量数据' : resourceMode ? '暂无链路资源记录' : '暂无用量记录'}</h2>
    <p>{pending ? '读取完成后会显示当前窗口的数据集用量。' : failed ? '请在页面上方重试，统计窗口会保留。' : `近 ${windowDays} 天内没有${resourceMode ? '模型或检索资源' : '助手消息'}记录。`}</p>
    {!pending && !failed ? <Link href="/" className={styles.emptyLink}>开始对话<ArrowUpRight /></Link> : null}
  </section>

  return <section aria-label={resourceMode ? '数据集链路资源' : '数据集用量归因'}>
    <p className={styles.scrollHint}><ChevronLeft />左右滑动查看全部字段<ChevronRight /></p>
    <div className={styles.tableScroll} tabIndex={0} role="region" aria-label="数据集用量表，可横向滚动">
      <table className={styles.table}>
        <caption className="sr-only">按{resourceMode ? '模型 token' : '助手 token'}从高到低排列；未取得的字段显示为破折号。</caption>
        <thead><tr><th scope="col" className={styles.datasetColumn}>数据集</th>
          {resourceMode ? <><th scope="col">LLM token</th><th scope="col">向量 token</th><th scope="col">向量字符</th><th scope="col">平均检索</th><th scope="col">重排总耗时</th></> : <><th scope="col">助手消息</th><th scope="col">助手 token</th><th scope="col">占比</th><th scope="col">向量 token</th><th scope="col">平均检索</th></>}
          <th scope="col" className={styles.actionColumn}>入口</th>
        </tr></thead>
        <tbody>{items.map(row => <tr key={row.key}>
          <th scope="row" className={styles.datasetColumn}><div className={styles.datasetIdentity}><span className={styles.datasetIcon}><Database /></span><div><strong title={row.datasetId ? `${row.name} · ${row.datasetId}` : row.name}>{row.name}</strong>
            {row.visibility === 'hidden' ? <small className={styles.hiddenLabel}>{shortDatasetId(row.datasetId!)}</small> : row.visibility === 'unresolved' ? <small>名称未取得</small> : null}
          </div></div></th>
          {resourceMode ? <><td>{formatCount(row.cost?.llm_total_tokens)}</td><td>{formatCount(row.cost?.embedding_query_tokens)}</td><td>{formatCount(row.cost?.embedding_query_chars)}</td><td>{formatDuration(averageRetrievalMs(row.cost?.retrieval_elapsed_sec_sum, row.cost?.assistant_messages))}</td><td>{formatDuration(row.cost?.rerank_elapsed_sec_sum == null ? null : row.cost.rerank_elapsed_sec_sum * 1000)}</td></> : <>
            <td>{formatCount(row.messages)}</td><td className={styles.emphasized}>{formatCount(row.assistantTokens)}</td>
            <td>{row.share === null ? '—' : <span className={styles.share}><span aria-hidden="true"><i style={{ width: `${Math.max(0, Math.min(100, row.share))}%` }} /></span>{formatCount(row.share, 1)}%</span>}</td>
            <td>{formatCount(row.cost?.embedding_query_tokens)}</td><td>{formatDuration(averageRetrievalMs(row.cost?.retrieval_elapsed_sec_sum, row.cost?.assistant_messages))}</td>
          </>}
          <td className={styles.actionColumn}>{row.href ? <Link href={row.href} className={styles.datasetLink} aria-label={`查看${row.name}知识库`}>查看知识库<ArrowUpRight /></Link> : <span className={styles.unavailable} aria-label="无可访问的知识库入口">—</span>}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <div className={styles.pagination}>
      <span>共 {rows.length} 个数据集</span><span className={styles.spacer} />
      {pageCount > 1 ? <><span>{(currentPage - 1) * COST_ATTRIBUTION_PAGE_SIZE + 1}–{Math.min(currentPage * COST_ATTRIBUTION_PAGE_SIZE, rows.length)} · {currentPage} / {pageCount}</span><Button variant="ghost" size="icon" aria-label="用量上一页" disabled={currentPage <= 1} onClick={() => onPageChange(currentPage - 1)}><ChevronLeft /></Button><Button variant="ghost" size="icon" aria-label="用量下一页" disabled={currentPage >= pageCount} onClick={() => onPageChange(currentPage + 1)}><ChevronRight /></Button></> : null}
      <span className={cn(styles.sortHint, pageCount > 1 && styles.pagedHint)}>按{resourceMode ? '模型' : '助手'} token 排序</span>
    </div>
  </section>
}
