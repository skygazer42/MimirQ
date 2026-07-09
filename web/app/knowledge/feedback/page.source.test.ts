import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('feedback page source', () => {
  it('routes through a no-SSR page shell to avoid production hydration drift', () => {
    const page = read('./page.tsx')

    expect(page).toContain("import dynamic from 'next/dynamic'")
    expect(page).toContain("const FeedbackTriagePageClient = dynamic(() => import('./page-client'), {")
    expect(page).toContain('ssr: false')
    expect(page).toContain('正在加载反馈分析中心...')
  })

  it('shows real feedback loop candidates from feedbackApi', () => {
    const src = read('./page-client.tsx')

    expect(src).toContain('feedbackApi.loopCandidates')
    expect(src).toContain('反哺候选')
    expect(src).toContain('HardNeg')
    expect(src).toContain('规则候选')
  })

  it('labels imported benchmark feedback as a first-class evaluation source', () => {
    const src = read('./page-client.tsx')

    expect(src).toContain("| 'benchmark'")
    expect(src).toContain("benchmark: '评测样本'")
    expect(src).toContain("raw.includes('benchmark')")
    expect(src).toContain("return 'benchmark'")
    expect(src).toContain("<SelectItem value=\"benchmark\">评测样本</SelectItem>")
    expect(src).toContain('item.extra?.feedback_issue')
  })

  it('uses real day-over-day feedback deltas instead of fixed placeholder percentages', () => {
    const src = read('./page-client.tsx')

    expect(src).toContain('function buildFeedbackDelta(')
    expect(src).toContain("todayKey = utcDayKey(now)")
    expect(src).toContain("yesterday.setUTCDate(yesterday.getUTCDate() - 1)")
    expect(src).toContain("label: `${change >= 0 ? '+' : ''}${change.toFixed(1)}%`")
    expect(src).toContain("label: today > 0 ? `昨日 0 / 今日 ${today}` : '暂无昨日基线'")
    expect(src).not.toContain("delta: '+12%'")
    expect(src).not.toContain("delta: '+8%'")
    expect(src).not.toContain("delta: '+21%'")
    expect(src).not.toContain("delta: '-5%'")
    expect(src).toContain('暂无高频原因，收到低分反馈后自动聚合 TOP3。')
    expect(src).toContain('暂无来源分布，收到真实反馈后自动统计。')
    expect(src).toContain('最近 7 天暂无反馈趋势，收到数据后会自动绘制曲线。')
  })

  it('defers relative timestamp chips until after mount and buckets trend stats by UTC day keys', () => {
    const src = read('./page-client.tsx')

    expect(src).toContain("const [timeReady, setTimeReady] = useState(false)")
    expect(src).toContain("useEffect(() => {\n    setTimeReady(true)\n  }, [])")
    expect(src).toContain("timeReady ? formatDate(item.created_at) : '—'")
    expect(src).toContain("timeReady ? formatDate(detail.updated_at) : '—'")
    expect(src).toContain('function utcDayKey(value: string | Date): string')
    expect(src).toContain('const dayKey = utcDayKey(day)')
    expect(src).toContain('const itemKey = utcDayKey(item.created_at)')
  })
})
