import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('settings page api error formatting', () => {
  it('uses formatApiError for backend failures (request_id included)', () => {
    const page = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    const hook = fs.readFileSync(path.resolve(__dirname, 'use-settings-page-state.ts'), 'utf8')

    expect(page).toContain('useSettingsPageState')
    expect(hook).toContain('formatApiError(')
    expect(hook).not.toContain('const err = error as any')
  })
})
