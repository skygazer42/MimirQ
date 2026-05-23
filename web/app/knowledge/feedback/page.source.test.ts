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
