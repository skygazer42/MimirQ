import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('parsing elements panel source', () => {
  it('supports kind filtering and element selection for direct review', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-elements-panel.tsx'), 'utf8')

    expect(src).toContain("const [filterKind, setFilterKind] = useState<string>('all')")
    expect(src).toContain('const visibleElements = useMemo(')
    expect(src).toContain('onSelectElement')
    expect(src).toContain('source_content_type')
    expect(src).toContain('bbox')
    expect(src).toContain('confidence')
    expect(src).toContain('结构元素列表')
    expect(src).toContain('全部')
  })
})
