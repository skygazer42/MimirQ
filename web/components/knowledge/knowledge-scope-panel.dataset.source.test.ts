import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('KnowledgeScopePanel dataset scope selector', () => {
  it('renders a collapsible dataset selector in the left scope panel instead of a persistent dropdown', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-scope-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, "useTranslations('KnowledgeScopePanel')")
    expectSourceToContain(src, 'aria-label={t("dataset.ariaLabel")}')
    expectSourceToContain(src, "t('dataset.all')")
    expectSourceToContain(
      src,
      'const [datasetListExpanded, setDatasetListExpanded] = useState(false)'
    )
    expectSourceToContain(src, 'aria-expanded={datasetListExpanded}')
    expectSourceToContain(src, 'role="group"')
    expectSourceToContain(src, 'aria-pressed={isActive}')
  })
})
