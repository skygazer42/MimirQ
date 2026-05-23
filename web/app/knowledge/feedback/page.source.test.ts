import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('feedback page source', () => {
  it('shows real feedback loop candidates from feedbackApi', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('feedbackApi.loopCandidates')
    expect(src).toContain('反哺候选')
    expect(src).toContain('HardNeg')
    expect(src).toContain('规则候选')
  })

  it('defers relative timestamp chips until after mount and buckets trend stats by UTC day keys', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("const [timeReady, setTimeReady] = useState(false)")
    expect(src).toContain("useEffect(() => {\n    setTimeReady(true)\n  }, [])")
    expect(src).toContain("timeReady ? formatDate(item.created_at) : '—'")
    expect(src).toContain("timeReady ? formatDate(detail.updated_at) : '—'")
    expect(src).toContain('function utcDayKey(value: string | Date): string')
    expect(src).toContain('const dayKey = utcDayKey(day)')
    expect(src).toContain('const itemKey = utcDayKey(item.created_at)')
  })
})
