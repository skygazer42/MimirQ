import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('settings page structure', () => {
  it('keeps the settings page as a thin shell over the dedicated state hook', () => {
    const page = read('./page.tsx')
    const hook = read('./use-settings-page-state.ts')

    expect(page).toContain('useSettingsPageState')
    expect(page).not.toContain('const DEFAULT_OBSERVABILITY')
    expect(page).not.toContain('const loadSettings = async () =>')
    expect(page).not.toContain('const registerLtrModel = async () =>')
    expect(hook).toContain('export function useSettingsPageState()')
    expect(hook).toContain('const DEFAULT_OBSERVABILITY')
    expect(hook).toContain('const loadSettings = async () =>')
  })
})
