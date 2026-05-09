import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('navbar source', () => {
  it('skips dev route prefetch in automated browsers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain("if (globalThis.navigator?.webdriver) return")
    expect(src).toContain('router.prefetch(href)')
  })

  it('uses locale-aware navigation helpers and has locale wrappers for navbar routes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')
    const webRoot = path.resolve(__dirname, '..')
    const wrapperPaths = [
      'app/[locale]/access-review/page.tsx',
      'app/[locale]/audit/page.tsx',
      'app/[locale]/auth/page.tsx',
      'app/[locale]/chunk-preview/page.tsx',
      'app/[locale]/data-governance/page.tsx',
      'app/[locale]/data-governance/common-lines/page.tsx',
      'app/[locale]/data-governance/profiles/page.tsx',
      'app/[locale]/datasets/page.tsx',
      'app/[locale]/diagnostics/page.tsx',
      'app/[locale]/evaluations/ablations/page.tsx',
      'app/[locale]/graph/page.tsx',
      'app/[locale]/graph/diagnostics/page.tsx',
      'app/[locale]/graph/snapshots/page.tsx',
      'app/[locale]/knowledge/feedback/page.tsx',
      'app/[locale]/knowledge/ingestion/page.tsx',
      'app/[locale]/knowledge/quarantine/page.tsx',
      'app/[locale]/knowledge/similarity/page.tsx',
      'app/[locale]/parsing/page.tsx',
      'app/[locale]/prompts/page.tsx',
      'app/[locale]/reports/page.tsx',
      'app/[locale]/settings/page.tsx',
      'app/[locale]/settings/groups/page.tsx',
      'app/[locale]/settings/rbac/page.tsx',
      'app/[locale]/usage/page.tsx',
    ]

    expect(src).toContain("import { Link, usePathname, useRouter } from '@/i18n/navigation'")
    expect(src).not.toContain("import Link from 'next/link'")
    expect(src).not.toContain("import { usePathname, useRouter } from 'next/navigation'")

    for (const wrapperPath of wrapperPaths) {
      expect(fs.existsSync(path.resolve(webRoot, wrapperPath))).toBe(true)
    }
  })

  it('declares translations for the navbar copy', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain("import { useTranslations } from 'next-intl'")
    expect(src).toContain("const t = useTranslations('Navbar')")
    expect(src).toContain("t('actions.newConversation')")
    expect(src).toContain("titleKey: 'sections.core'")
    expect(src).toContain('t(section.titleKey)')
    expect(src).toContain("t('command.triggerLabel')")
  })

  it('filters system navigation by tenant permissions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain("import { useTenantAccess } from '@/hooks/use-tenant-access'")
    expect(src).toContain('requiredPermission: TENANT_PERMISSIONS.OBSERVABILITY_READ')
    expect(src).toContain('requiredPermission: TENANT_PERMISSIONS.USAGE_READ')
    expect(src).toContain('requiredPermission: TENANT_PERMISSIONS.AUDIT_READ')
    expect(src).toContain('requiredPermission: TENANT_PERMISSIONS.SETTINGS_READ')
    expect(src).toContain('visibleMenuSections')
    expect(src).toContain('tenantAccessAllows(tenantAccess.data, permission)')
  })

  it('keeps the expanded sidebar width aligned with the 2048px dashboard layout reference', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain('w-[264px] translate-x-0')
    expect(src).toContain('w-[264px] -translate-x-full')
    expect(src).toContain('left-[264px]')
  })
})
