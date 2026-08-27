import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readWorkspaceFile(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, '../../..', relativePath), 'utf8')
}

function readConstValue(source: string, constName: string): string {
  const match = source.match(new RegExp(`const\\s+${constName}\\s*=\\s*'([^']*)'`))

  expect(match, `missing ${constName}`).not.toBeNull()
  return match?.[1] ?? ''
}

describe('dataset detail surface shells', () => {
  it('keeps toolbar, panel, and CTA classes flat on dataset detail pages', () => {
    const routeClassContracts: Array<{
      routeFile: string
      constants: Record<string, RegExp[]>
    }> = [
      {
        routeFile: 'app/datasets/[id]/health/page-client.tsx',
        constants: {
          healthPanelClass: [/linear-gradient/, /ring-1/, /shadow-\[/],
          healthToolbarGroupClass: [/rounded-2xl/, /ring-1/, /shadow-\[/, /backdrop-blur/],
          healthToolbarExportButtonClass: [/shadow-\[/],
          healthToolbarPrimaryButtonClass: [/linear-gradient/, /shadow-\[/],
        },
      },
      {
        routeFile: 'app/datasets/[id]/profile/page-client.tsx',
        constants: {
          profilePanelClass: [/linear-gradient/, /ring-1/, /shadow-\[/],
          profileToolbarGroupClass: [/rounded-2xl/, /ring-1/, /shadow-\[/, /backdrop-blur/],
          profileToolbarExportButtonClass: [/shadow-\[/],
          profileToolbarPrimaryButtonClass: [/linear-gradient/, /shadow-\[/],
        },
      },
      {
        routeFile: 'app/datasets/[id]/precheck/page-client.tsx',
        constants: {
          precheckToolbarGroupClass: [/rounded-2xl/, /ring-1/, /shadow-\[/, /backdrop-blur/],
          precheckToolbarExportButtonClass: [/shadow-\[/],
          precheckToolbarPrimaryButtonClass: [/linear-gradient/, /shadow-\[/],
        },
      },
      {
        routeFile: 'app/datasets/[id]/ingestion/page.tsx',
        constants: {
          ingestionToolbarGroupClass: [/rounded-2xl/, /ring-1/, /shadow-\[/, /backdrop-blur/],
          ingestionToolbarPrimaryButtonClass: [/shadow-\[/],
          ingestionPanelClass: [/rounded-\[24px\]/, /ring-1/, /shadow-\[/, /backdrop-blur/],
          ingestionPanelHeaderClass: [/linear-gradient/],
          ingestionIconPillClass: [/rounded-2xl/, /shadow-\[/],
          ingestionActionButtonClass: [/shadow-(?:sm|md|lg|xl|2xl|\[)/],
          ingestionMetricCardClass: [/rounded-2xl/, /ring-1/, /shadow-\[/],
        },
      },
      {
        routeFile: 'app/datasets/[id]/tables/page.tsx',
        constants: {
          tableToolbarGroupClass: [/rounded-2xl/, /ring-1/, /shadow-\[/, /backdrop-blur/],
          tablePanelClass: [/rounded-\[24px\]/, /ring-1/, /shadow-\[/, /backdrop-blur/],
          tablePanelHeaderClass: [/linear-gradient/],
          tableMetricCardClass: [/rounded-2xl/, /ring-1/, /shadow-\[/],
          tableIconPillClass: [/rounded-2xl/, /shadow-\[/],
        },
      },
      {
        routeFile: 'app/datasets/[id]/workflow/page.tsx',
        constants: {
          workflowActionButtonClass: [/shadow-\[/],
          workflowPanelClass: [/linear-gradient/, /ring-1/, /shadow-\[/],
        },
      },
      {
        routeFile: 'app/datasets/[id]/db-catalog/page.tsx',
        constants: {
          dbCatalogPanelClass: [/linear-gradient/, /ring-1/, /shadow-\[/],
          dbCatalogActionButtonClass: [/shadow-\[/],
        },
      },
    ]

    for (const { routeFile, constants } of routeClassContracts) {
      const src = readWorkspaceFile(routeFile)

      for (const [constName, forbiddenPatterns] of Object.entries(constants)) {
        const classValue = readConstValue(src, constName)

        for (const forbiddenPattern of forbiddenPatterns) {
          expect(classValue, `${routeFile}:${constName}`).not.toMatch(forbiddenPattern)
        }
      }
    }
  })

  it('removes remaining inline glass-shell treatments from precheck and detail CTA surfaces', () => {
    const precheckSource = readWorkspaceFile('app/datasets/[id]/precheck/page-client.tsx')
    const workflowSource = readWorkspaceFile('app/datasets/[id]/workflow/page.tsx')
    const dbCatalogSource = readWorkspaceFile('app/datasets/[id]/db-catalog/page.tsx')

    expect(precheckSource).not.toContain(
      'className="h-full overflow-hidden border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)/0.98),hsl(var(--background)/0.92))] p-0 shadow-[0_16px_45px_rgba(15,23,42,0.07)] ring-1 ring-border/50 dark:border-border/60 dark:bg-card/95 dark:ring-white/5"'
    )
    expect(precheckSource).not.toContain(
      'className="h-full overflow-hidden border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)/0.96),hsl(var(--background)/0.9))] p-0 shadow-[0_16px_45px_rgba(15,23,42,0.065)] ring-1 ring-border/50 dark:border-border/60 dark:bg-card/95 dark:ring-white/5"'
    )
    expect(workflowSource).not.toContain(
      'className="h-10 min-w-[118px] gap-2 rounded-xl bg-[linear-gradient(90deg,hsl(var(--primary)),hsl(var(--info)))] text-[13px] text-primary-foreground shadow-[0_14px_30px_rgba(20,184,166,0.24)] hover:bg-[linear-gradient(90deg,hsl(var(--primary)/0.92),hsl(var(--info)/0.92))]"'
    )
    expect(dbCatalogSource).not.toContain(
      'className="h-10 min-w-[118px] gap-2 rounded-xl bg-[linear-gradient(90deg,hsl(var(--primary)),hsl(var(--info)))] text-[13px] text-primary-foreground shadow-[0_14px_30px_hsl(var(--info)/0.24)] hover:bg-[linear-gradient(90deg,hsl(var(--primary)/0.92),hsl(var(--info)/0.92))]"'
    )
  })
})
