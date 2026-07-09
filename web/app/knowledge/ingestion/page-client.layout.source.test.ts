import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('knowledge ingestion dual-mode layout', () => {
  it('defaults to sales-audit mode and exposes a full skeleton switch for execution-monitor', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'page-client.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'data-page-scroll-container="true"')
    expectSourceToContain(src, 'data-ingestion-page-root="true"')
    expectSourceToContain(src, 'INGESTION_BACKGROUND_CLASS')
    expectSourceToContain(src, 'INGESTION_HERO_PANEL_CLASS')
    expectSourceToContain(
      src,
      'flex-1 h-full min-h-0 overflow-y-auto overscroll-contain no-scrollbar scroll-fade-bottom'
    )
    expectSourceToContain(src, 'max-w-none')
    expectSourceToContain(
      src,
      "type IngestionMode = 'sales-audit' | 'execution-monitor'"
    )
    expectSourceToContain(
      src,
      "searchParams.get('mode') === 'execution-monitor' ? 'execution-monitor' : 'sales-audit'"
    )
    expectSourceToContain(src, '入库预检工作台')
    expectSourceToContain(src, '执行监控')
    expectSourceToContain(src, '入库建议')
    expectSourceToContain(src, '抽样确认量')
    expectSourceToContain(src, 'PDF 类型分流')
    expectSourceToContain(src, '文档长度分布（按字符数）')
    expectSourceToContain(src, '版本冲突')
    expectSourceToContain(src, '入库预检报告')
    expectSourceToContain(src, '正式入库')
    expectSourceToContain(src, 'triggerFilePicker({ precheckOnly: false })')
    expectSourceToContain(src, 'triggerFilePicker({ precheckOnly: true })')
    expectSourceToContain(src, 'onUploadSample={handleUploadSampleAssessment}')
    expectSourceToContain(src, 'onUploadIngest={handleUploadFormalIngest}')
    expectSourceToContain(src, '核心摘要')
    expectSourceToContain(src, '风险热区（按风险类型）')
    expectSourceToContain(src, '处理清单（待处理文件数）')
    expectSourceToContain(src, '入库抽样确认')
    expectSourceToContain(src, '高风险文件（示例）')
    expectSourceToContain(src, '扫描件')
    expectSourceToContain(src, '解析失败')
    expectSourceToContain(src, '合敏感信息')
    expectSourceToContain(src, '重复文件')
    expectSourceToContain(src, '其他风险')
    expectSourceToContain(src, 'OCR 处理')
    expectSourceToContain(src, '格式转换')
    expectSourceToContain(src, '人工审核')
    expectSourceToContain(src, '去重处理')
    expectSourceNotToContain(src, '打开 Demo')
    expectSourceToContain(src, '退出演示')
    expectSourceToContain(src, '入库依据')
    expectSourceToContain(src, '复杂度细节')
    expectSourceToContain(src, '入库抽样确认')
    expectSourceToContain(src, '高风险文件（示例）')
    expectSourceToContain(src, 'text-[clamp(1.45rem,2.4vw,2.4rem)]')
    expectSourceToContain(src, 'h-9 rounded-xl')
    expectSourceToContain(src, 'rounded-[1.6rem]')
    expectSourceToContain(src, 'p-3.5 md:p-4')
    expectSourceToContain(
      src,
      'const [desktopScopeCollapsed, setDesktopScopeCollapsed] = useState(true)'
    )
    expectSourceToContain(
      src,
      "const showDesktopAuditRail = mode === 'execution-monitor' && !showEmptyState && !desktopScopeCollapsed"
    )
    expectSourceToContain(
      src,
      "const showDesktopAuditRailToggle = mode === 'execution-monitor' && !showEmptyState"
    )
    expectSourceToContain(
      src,
      'const [headerCollapsed, setHeaderCollapsed] = useState(false)'
    )
    expectSourceToContain(
      src,
      "const [auditDispositionFilter, setAuditDispositionFilter] = useState<AuditDispositionFilter>('all')"
    )
    expectSourceToContain(src, 'const node = scrollContainerRef.current')
    expectSourceToContain(
      src,
      "node.addEventListener('scroll', handleScroll, { passive: true })"
    )
    expectSourceToContain(
      src,
      "showDesktopAuditRailToggle ? 'lg:flex' : 'lg:hidden'"
    )
    expectSourceToContain(src, 'opacity-0 hover:opacity-100 focus-visible:opacity-100')
    expectSourceToContain(src, '[writing-mode:vertical-rl]')
    expectSourceToContain(src, '>范围</span>')
    expectSourceNotToContain(src, '<ChevronRight className="h-4 w-4" />')
    expectSourceToContain(
      src,
      "showDesktopAuditRail ? 'w-[15.5rem] opacity-100' : 'w-0 opacity-0 -translate-x-4 pointer-events-none'"
    )
    expectSourceToContain(src, 'const auditRailCounts = useMemo(() => {')
    expectSourceToContain(
      src,
      'aria-pressed={auditDispositionFilter === value}'
    )
    expectSourceToContain(
      src,
      'onClick={() => setAuditDispositionFilter(value)}'
    )
    expectSourceToContain(src, "['pending', '待确认', auditRailCounts.pending")
    expectSourceToContain(src, "['manual', '人工处理', auditRailCounts.manual")
    expectSourceToContain(
      src,
      "['approved', '已确认', auditRailCounts.approved"
    )
    expectSourceToContain(src, '共 {visibleAuditSamples.length} 项线索')
    expectSourceToContain(src, 'backdrop-blur-xl')
    expectSourceToContain(
      src,
      'bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)]'
    )
    expectSourceToContain(src, 'handleExportSalesAuditReport')
    expectSourceToContain(src, 'taskQueueSnapshot')
    expectSourceToContain(src, 'recentQueueOutcomes')
    expectSourceNotToContain(src, 'handleRefreshExecutionMonitor')
    expectSourceNotToContain(src, '刷新运行态')
    expectSourceToContain(src, '处理模式')
    expectSourceToContain(src, '当前吞吐')
    expectSourceToContain(src, "mode === 'sales-audit'")
    expectSourceToContain(
      src,
      "searchParams.get('mode') === 'execution-monitor'"
    )
    expectSourceNotToContain(src, "['sales-audit', '样本评估']")
    expectSourceNotToContain(src, "['execution-monitor', '执行监控']")
    expectSourceNotToContain(src, 'onClick={() => handleChangeMode(value)}')
    expectSourceNotToContain(src, '样本评估')
    expectSourceToContain(src, 'IngestionViewSwitch')
    expectSourceNotToContain(src, '清隐已处理')
    expectSourceNotToContain(src, 'text-[clamp(1.8rem,3vw,3rem)]')
    expectSourceNotToContain(src, 'h-10 rounded-2xl')
    expectSourceToContain(src, 'rounded-[28px] border border-sky-200/55')
    expectSourceToContain(src, 'via-sky-300/65')
    expectSourceToContain(src, '<PageTitleIcon name="ingestion-monitor" className="size-9" />')
  })
})
