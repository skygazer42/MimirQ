import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ui audit scripts', () => {
  it('keeps contrast and bundle budget guards wired into package scripts', () => {
    const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['ui-check']).toContain('check-theme-contrast.mjs')
    expect(pkg.scripts?.build).toContain('check-bundle-budget.mjs')
    expect(fs.existsSync(path.resolve(__dirname, 'check-theme-contrast.mjs'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'check-bundle-budget.mjs'))).toBe(true)
  })

  it('skips bundled vendor assets when scanning for native dialogs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'check-native-dialogs.mjs'), 'utf8')

    expect(src).toContain('path.join("public", "monaco")')
  })
})
