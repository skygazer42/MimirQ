import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl shared pathname routing source', () => {
  it('uses locale-aware pathname/link helpers across shared route-aware components', () => {
    const breadcrumb = read('components/ui/breadcrumb.tsx')
    const routeScrollReset = read('components/route-scroll-reset.tsx')
    const webVitalsReporter = read('components/providers/web-vitals-reporter.tsx')
    const fluidCursor = read('components/ui/fluid-cursor.tsx')
    const ingestionWorkflowStepper = read('components/ui/ingestion-workflow-stepper.tsx')

    expect(breadcrumb).toContain("import { Link, usePathname } from '@/i18n/navigation'")
    expect(breadcrumb).not.toContain("import Link from 'next/link'")
    expect(breadcrumb).not.toContain("import { usePathname } from 'next/navigation'")

    expect(routeScrollReset).toContain("import { usePathname } from '@/i18n/navigation'")
    expect(routeScrollReset).not.toContain("import { usePathname } from 'next/navigation'")

    expect(webVitalsReporter).toContain("import { usePathname } from '@/i18n/navigation'")
    expect(webVitalsReporter).not.toContain("import { usePathname } from 'next/navigation'")

    expect(fluidCursor).toContain('from "@/i18n/navigation"')
    expect(fluidCursor).not.toContain('from "next/navigation"')

    expect(ingestionWorkflowStepper).toContain("import { Link, usePathname } from '@/i18n/navigation'")
    expect(ingestionWorkflowStepper).not.toContain("import Link from 'next/link'")
    expect(ingestionWorkflowStepper).not.toContain("import { usePathname } from 'next/navigation'")
  })

  it('keeps page-transition on next/navigation because app/template renders during global-error prerendering', () => {
    const pageTransition = read('components/page-transition.tsx')

    expect(pageTransition).toContain('from "next/navigation"')
    expect(pageTransition).not.toContain('from "@/i18n/navigation"')
  })
})
