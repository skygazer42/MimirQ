import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings switch', () => {
  it('uses distinct checked and unchecked states for settings toggles', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'settings-switch.tsx'), 'utf8')

    expect(src).toContain('w-20')
    expect(src).toContain("before:content-['停用']")
    expect(src).toContain("after:content-['启用']")
    expect(src).toContain('data-[switch-state=checked]:before:text-muted-foreground/65')
    expect(src).toContain('data-[switch-state=checked]:after:text-primary-foreground')
    expect(src).toContain('data-[switch-state=checked]:bg-primary/15')
    expect(src).toContain('data-[switch-state=unchecked]:border-border')
    expect(src).toContain('data-[switch-state=unchecked]:bg-muted/65')
    expect(src).toContain('data-[switch-state=unchecked]:before:text-foreground/80')
    expect(src).toContain('data-[switch-state=unchecked]:after:text-muted-foreground/65')
    expect(src).toContain('data-[switch-state=checked]:[&>span]:bg-primary')
    expect(src).not.toContain('data-[switch-state=checked]:[&>span]:bg-gradient-to-r')
    expect(src).not.toContain('data-[switch-state=checked]:[&>span]:from-primary')
    expect(src).not.toContain('data-[switch-state=checked]:[&>span]:to-accent')
    expect(src).toContain('data-[switch-state=unchecked]:[&>span]:bg-background')
    expect(src).toContain('data-switch-state=')
    expect(src).toContain('SettingsSwitchIndicator')
  })

  it('keeps settings overview cards on the shared switch indicator', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '../../app/settings/page.tsx'),
      'utf8'
    )

    expect(src).toContain('SettingsSwitchIndicator')
    expect(src).not.toContain('function SettingsToggleIndicator')
    expect(src).not.toContain("'flex h-5 w-9 shrink-0 items-center rounded-full")
  })

  it('keeps settings sections off native checkbox toggles', () => {
    const settingsDir = path.resolve(__dirname, '../../app/settings')
    const filesToCheck = [
      '_sections/rag-section.tsx',
      '_sections/governance-section.tsx',
      '_sections/url-ingest-section.tsx',
      '_sections/navigation-visibility-section.tsx',
      '_sections/runtime-controls-section.tsx',
      '_sections/observability-section.tsx',
      '_sections/dify-integration-section.tsx',
      '_sections/parser-services-section.tsx',
    ]

    for (const file of filesToCheck) {
      const src = fs.readFileSync(path.join(settingsDir, file), 'utf8')
      expect(src, file).not.toContain('type="checkbox"')
      expect(src, file).not.toContain("type='checkbox'")
    }
  })

  it('keeps parser service toggles on the shared settings switch', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '../../app/settings/_sections/parser-services-section.tsx'),
      'utf8'
    )

    expect(src).toContain("import { SettingsSwitch } from '@/components/settings/settings-switch'")
    expect(src).toContain('<SettingsSwitch')
    expect(src).not.toContain('已开启')
    expect(src).not.toContain('已关闭')
  })

  it('keeps pipeline toggles at readable settings switch size', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '../pipeline-options-panel.tsx'),
      'utf8'
    )

    expect(src).not.toContain('scale-75')
    expect(src).not.toContain('scale-90')
  })
})
