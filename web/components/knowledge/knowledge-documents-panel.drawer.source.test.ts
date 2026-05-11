import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('KnowledgeDocumentsPanel inspector drawer', () => {
  it('opens document details in a right-side drawer instead of consuming permanent table width', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-documents-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(
      src,
      'const [activeDrawerDoc, setActiveDrawerDoc] = useState<Document | null>(null)'
    )
    expectSourceToContain(src, 'open={Boolean(activeDrawerDoc)}')
    expectSourceToContain(src, 'onOpenChange={handleDrawerOpenChange}')
    expectSourceToContain(
      src,
      'left-auto right-0 top-0 h-dvh w-[min(480px,100vw)] max-w-[480px] translate-x-0 translate-y-0 rounded-none p-0 overflow-hidden'
    )
    expectSourceToContain(
      src,
      '<KnowledgeInspector embedded selectedDocs={activeDrawerDoc ? [activeDrawerDoc] : []} />'
    )
  })
})
