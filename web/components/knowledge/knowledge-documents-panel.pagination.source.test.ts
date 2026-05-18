import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Knowledge documents pagination', () => {
  it('uses real parent-owned pagination instead of a static footer', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-page.tsx'),
      'utf8'
    )
    const panelSrc = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-documents-panel.tsx'),
      'utf8'
    )

    expect(pageSrc).toContain('const DOCUMENTS_PAGE_SIZE = 20')
    expect(pageSrc).toContain('const [documentsPage, setDocumentsPage] = useState(1)')
    expect(pageSrc).toContain('const paginatedDocuments = useMemo(')
    expect(pageSrc).toContain('count: paginatedDocuments.length')
    expect(pageSrc).toContain('filteredDocuments={paginatedDocuments}')
    expect(pageSrc).toContain('totalDocumentsCount={filteredDocuments.length}')
    expect(pageSrc).toContain('onPageChange={setDocumentsPage}')

    expect(panelSrc).toContain('const canGoPrevious = page > 1')
    expect(panelSrc).toContain('const canGoNext = page < pageCount')
    expect(panelSrc).toContain('第 {page} / {pageCount} 页')
    expect(panelSrc).toContain('onClick={() => onPageChange(page - 1)}')
    expect(panelSrc).toContain('onClick={() => onPageChange(page + 1)}')
    expect(panelSrc).not.toContain('<span className="inline-flex h-9 min-w-9 items-center justify-center rounded-[12px] bg-primary px-3 text-[12px] font-medium text-primary-foreground">\\n                        1\\n                      </span>')
  })
})
