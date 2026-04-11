import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('parsing extract panel source', () => {
  it('supports schema and prompt extraction modes with runtime API calls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-extract-panel.tsx'), 'utf8')

    expect(src).toContain("from '@/lib/api'")
    expect(src).toContain("const [mode, setMode] = useState<'schema' | 'prompt'>('schema')")
    expect(src).toContain('onSelectEvidence?:')
    expect(src).toContain('parsingApi.extract(')
    expect(src).toContain('onSelectEvidence?.(')
    expect(src).toContain('evidence.pages')
    expect(src).toContain('source_visual_kind')
    expect(src).toContain('const availableVisualKinds = useMemo(')
    expect(src).toContain('来源 visual kind')
    expect(src).toContain('跨页')
    expect(src).toContain('运行抽取')
    expect(src).toContain('抽取结果')
    expect(src).toContain('Prompt')
    expect(src).toContain('Schema')
  })
})
