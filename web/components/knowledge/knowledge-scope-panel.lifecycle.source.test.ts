import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('KnowledgeScopePanel lifecycle filter', () => {
  it('owns the lifecycle <Select> control', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-scope-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, "useTranslations('KnowledgeScopePanel')")
    expectSourceToContain(src, 'aria-label={t("lifecycle.ariaLabel")}')
    expectSourceToContain(src, 't("lifecycle.active")')
    expectSourceToContain(src, 't("lifecycle.archived")')
  })
})
