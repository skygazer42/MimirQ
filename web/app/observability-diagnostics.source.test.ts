import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('observability and diagnostics source', () => {
  it('uses integer thresholds for observability presets', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'observability/page.tsx'), 'utf8')

    expect(src).toContain("{ label: '≥ 1s', value: 1 }")
    expect(src).toContain("{ label: '≥ 2s', value: 2 }")
    expect(src).toContain("{ label: '≥ 5s', value: 5 }")
    expect(src).toContain('const [slowThresholdSec, setSlowThresholdSec] = useState<number>(2)')
  })

  it('uses modern clipboard and string helpers in diagnostics', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'diagnostics/page.tsx'), 'utf8')

    expect(src).toContain("async function copyToClipboard(text = ''): Promise<void> {")
    expect(src).not.toContain('document.execCommand(')
    expect(src).not.toContain('removeChild(')
    expect(src).toContain(".join(String.raw`\\n`)")
  })

  it('renders a diagnostics-specific loading shell', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'diagnostics/page.tsx'), 'utf8')

    expect(src).toContain('PageLoading')
    expect(src).toContain('正在加载诊断中心...')
    expect(src).not.toContain('<div className="min-h-dvh bg-background" />')
  })
})
