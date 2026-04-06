import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel inspector drawer', () => {
  it('opens document details in a right-side drawer instead of consuming permanent table width', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('const [activeDrawerDoc, setActiveDrawerDoc] = useState<Document | null>(null)')
    expect(src).toContain('<Dialog open={Boolean(activeDrawerDoc)} onOpenChange={handleDrawerOpenChange}>')
    expect(src).toContain('left-auto right-0 top-0 h-dvh w-[min(480px,100vw)] max-w-[480px] translate-x-0 translate-y-0 rounded-none p-0 overflow-hidden')
    expect(src).toContain('<KnowledgeInspector embedded selectedDocs={activeDrawerDoc ? [activeDrawerDoc] : []} />')
  })
})
