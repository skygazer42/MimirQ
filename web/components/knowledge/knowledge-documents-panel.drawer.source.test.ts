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
      'left-auto right-0 top-0 flex h-dvh w-[min(540px,100vw)] max-w-[540px] translate-x-0 translate-y-0 flex-col gap-0'
    )
    expectSourceToContain(src, '文档审查视图')
    expectSourceToContain(src, 'border-l border-border/55')
    expectSourceToContain(
      src,
      '<KnowledgeInspector embedded selectedDocs={activeDrawerDoc ? [activeDrawerDoc] : []} />'
    )
  })
})
