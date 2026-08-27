// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

function readLocal(fileName: string) {
  return fs.readFileSync(path.resolve(__dirname, fileName), 'utf8')
}

describe('settings domain visual boundary contract', () => {
  it('keeps governance operations on the shared flat baseline', () => {
    const src = readLocal('governance-ops-panel.tsx')

    expectSourceToContain(src, '<Panel padding="md" className="border-foreground/10 bg-background shadow-none">')
    expectSourceNotToContain(src, 'rounded-full border border-primary/20 bg-primary/10')
  })

  it('removes floating treatment from danger and identity ops panels', () => {
    const dangerZone = readLocal('danger-zone-panel.tsx')
    const saml = readLocal('saml-ops-panel.tsx')
    const scim = readLocal('scim-provisioning-panel.tsx')

    expectSourceNotToContain(dangerZone, 'shadow-[0_8px_24px_hsl(var(--foreground)/0.04)]')
    expectSourceNotToContain(dangerZone, 'shadow-[0_8px_24px_hsl(var(--destructive)/0.035)]')
    expectSourceToContain(saml,
      "const SAML_PANEL_CLASS = 'overflow-hidden rounded-xl border border-foreground/10 bg-background shadow-none'"
    )
    expectSourceToContain(scim,
      "const SCIM_PANEL_CLASS = 'overflow-hidden rounded-xl border border-foreground/10 bg-background shadow-none'"
    )
    expectSourceNotToContain(saml, 'rounded-[1.25rem]')
    expectSourceNotToContain(scim, 'rounded-[1.25rem]')
  })
})
