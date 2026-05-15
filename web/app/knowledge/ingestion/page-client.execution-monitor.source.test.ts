import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('knowledge ingestion execution monitor chrome', () => {
  it('keeps the execution monitor focused on live runtime state', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'page-client.tsx'),
      'utf8'
    )

    expectSourceToContain(src, "const showSalesPolicyBadge = mode === 'sales-audit'")
    expectSourceToContain(src, "showSalesPolicyBadge ? (")
    expectSourceToContain(src, "mode === 'sales-audit' ? '入库预检工作台' : '执行监控'")
    expectSourceToContain(src, "label: '监控范围'")
    expectSourceToContain(src, "label: '处理模式'")
    expectSourceToContain(src, 'taskQueueSnapshot.enabled')
    expectSourceToContain(src, 'recentThroughputDetail')
    expectSourceToContain(src, '运行信息汇聚')
    expectSourceToContain(src, "mode === 'execution-monitor' ? 'py-3 md:py-3.5' : 'py-0'")
    expectSourceToContain(src, 'const EXECUTION_TASK_PAGE_SIZE = 5')
    expectSourceToContain(src, 'const [executionTaskPage, setExecutionTaskPage] = useState(1)')
    expectSourceToContain(src, 'const executionTaskPageCount = useMemo(')
    expectSourceToContain(src, 'const visibleExecutionTaskRows = useMemo(')
    expectSourceToContain(src, 'visibleExecutionTaskRows.map((document) => {')
    expectSourceToContain(src, '共 {executionTaskRows.length} 条')
    expectSourceToContain(src, '上一页')
    expectSourceToContain(src, '第 {executionTaskPage} /')
    expectSourceToContain(src, '{executionTaskPageCount} 页')
    expectSourceToContain(src, '下一页')
    expectSourceToContain(src, 'executionKpiCards.map((item) => {')
    expectSourceToContain(src, "label: '当前吞吐'")
    expectSourceToContain(src, "label: '平均处理耗时'")
    expectSourceToContain(src, "label: 'OCR 使用率'")
    expectSourceToContain(src, "'relative overflow-hidden rounded-[1.45rem] border border-border/60 bg-background/86 p-3 shadow-[0_28px_72px_-46px_rgba(15,23,42,0.32)] md:p-3.5'")
    expectSourceNotToContain(src, "detail: '全部项目'")
    expectSourceNotToContain(src, "detail: '待确认清单'")
    expectSourceNotToContain(src, "detail: '近 5 min'")
    expectSourceNotToContain(src, '运行态总览')
    expectSourceNotToContain(src, '联动下方风险、流水线与日志')
    expectSourceNotToContain(src, '质量指标（实时）')
    expectSourceNotToContain(src, 'executionTopStripItems.map')
    expectSourceNotToContain(src, "'border-t border-border/35 pt-2.5'")
    expectSourceNotToContain(src, '上传并入库')
    expectSourceNotToContain(src, "mode === 'sales-audit' ? 'min-h-[3.4rem]' : 'min-h-[3.4rem]'")
    expectSourceNotToContain(src, "label: '运行时长'")
    expectSourceNotToContain(src, 'executionRuntimeLabel')
    expectSourceNotToContain(src, '2xl:grid-cols-8')
    expectSourceNotToContain(src, '<LiveVelocity')
  })
})
