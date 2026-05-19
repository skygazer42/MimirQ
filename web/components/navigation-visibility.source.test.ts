import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const WEB_ROOT = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(WEB_ROOT, relativePath), 'utf8')
}

describe('admin controlled navigation visibility wiring', () => {
  it('filters the sidebar and command menu through the backend RBAC navigation policy', () => {
    const navbar = read('components/navbar.tsx')
    const commandMenu = read('components/command-menu.tsx')

    expect(navbar).toContain("import { canShowAdminControlledNavigationModule")
    expect(navbar).toContain("visibilityKey: 'knowledgeGraph'")
    expect(navbar).toContain("visibilityKey: 'graphSnapshots'")
    expect(navbar).toContain("visibilityKey: 'graphDiagnostics'")
    expect(navbar).toContain("visibilityKey: 'ragas'")
    expect(navbar).toContain("visibilityKey: 'ablations'")
    expect(navbar).toContain("visibilityKey: 'reports'")
    expect(navbar).toContain("visibilityKey: 'prompts'")
    expect(navbar).toContain("visibilityKey: 'governanceProfiles'")
    expect(navbar).toContain("visibilityKey: 'commonLines'")
    expect(navbar).toContain('canShowNavigationModule(item.visibilityKey)')

    expect(commandMenu).toContain("import { canShowAdminControlledNavigationModule")
    expect(commandMenu).toContain("visibilityKey: 'knowledgeGraph'")
    expect(commandMenu).toContain("visibilityKey: 'reports'")
    expect(commandMenu).toContain('canShowNavigationModule(command.visibilityKey)')
  })

  it('wraps directly reachable advanced pages in the same visibility gate', () => {
    const guardedRoutes = [
      ['app/graph/page.tsx', 'knowledgeGraph'],
      ['app/graph/snapshots/page.tsx', 'graphSnapshots'],
      ['app/graph/diagnostics/page.tsx', 'graphDiagnostics'],
      ['app/evaluations/page.tsx', 'ragas'],
      ['app/evaluations/ablations/page.tsx', 'ablations'],
      ['app/reports/page.tsx', 'reports'],
      ['app/prompts/page.tsx', 'prompts'],
      ['app/data-governance/profiles/page.tsx', 'governanceProfiles'],
      ['app/data-governance/common-lines/page.tsx', 'commonLines'],
    ] as const

    for (const [route, key] of guardedRoutes) {
      const src = read(route)
      expect(src, route).toContain("NavigationVisibilityGate")
      expect(src, route).toContain(`moduleKey="${key}"`)
    }
  })

  it('keeps the direct route visibility gate hydration-stable', () => {
    const gate = read('components/auth/navigation-visibility-gate.tsx')

    expect(gate).toContain('const [hasHydrated, setHasHydrated] = useState(false)')
    expect(gate).toContain('const allowed = hasHydrated && canShowAdminControlledNavigationModule(access.data, moduleKey)')
    expect(gate).toContain('if (!hasHydrated || access.isLoading)')
  })

  it('adds a real backend-backed settings section instead of a local-only fake switch', () => {
    const settingsPage = read('app/settings/page.tsx')
    const stateHook = read('app/settings/use-settings-page-state.ts')
    const section = read('app/settings/_sections/navigation-visibility-section.tsx')

    expect(settingsPage).toContain("import { NavigationVisibilitySection }")
    expect(settingsPage).toContain("id: 'sec-navigation'")
    expect(settingsPage).toContain('<NavigationVisibilitySection')
    expect(stateHook).toContain('navigationMerged')
    expect(stateHook).toContain('updateNavigation')
    expect(section).toContain('普通用户入口显示')
    expect(section).toContain('aria-label="查看普通用户入口显示说明"')
    expect(section).toContain('group-hover/nav-entry-help:block')
    expect(section).toContain('md:left-full')
    expect(section).toContain('md:-translate-y-1/2')
    expect(section).toContain('SettingsSwitch')
    expect(section).toContain('后端 /settings')
    expect(section).not.toContain('localStorage')
  })
})
