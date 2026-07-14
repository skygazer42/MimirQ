// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('PageTitleIcon theme behavior', () => {
  it('lets neutral mode desaturate decorative page art without affecting brand assets', () => {
    const component = fs.readFileSync(path.resolve(__dirname, 'page-title-icon.tsx'), 'utf8')
    const globals = fs.readFileSync(path.resolve(__dirname, '../../app/globals.css'), 'utf8')

    expect(component).toContain('data-theme-illustration="page-title"')
    expect(globals).toContain(
      'html:not(.dark)[data-surface-theme="neutral"] [data-theme-illustration="page-title"]'
    )
    expect(globals).toContain('filter: grayscale(1)')
  })
})
