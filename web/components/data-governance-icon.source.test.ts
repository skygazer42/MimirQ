import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (file: string) =>
  fs.readFileSync(path.resolve(__dirname, file), 'utf8')

describe('data governance generated icon', () => {
  it('uses the same generated asset in the page title and intake visual', () => {
    const panel = read('data-governance-panel.tsx')

    expect(panel).toContain("import Image from 'next/image'")
    expect(panel).toContain('iconImage="data-governance"')
    expect(panel).toContain(
      'src="/page-title-icons/data-governance.png"'
    )
    expect(panel).toContain('className="relative size-24 object-contain"')
    expect(panel).not.toContain('<Upload className="size-7" />')
  })

  it('keeps a high-resolution transparent PNG for crisp multi-size rendering', () => {
    const icon = fs.readFileSync(
      path.resolve(__dirname, '../public/page-title-icons/data-governance.png')
    )

    expect(icon.subarray(1, 4).toString('ascii')).toBe('PNG')
    expect(icon.readUInt32BE(16)).toBeGreaterThanOrEqual(1024)
    expect(icon.readUInt32BE(20)).toBeGreaterThanOrEqual(1024)
    expect(icon[25]).toBe(6)
  })
})
