import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readOperationSource() {
  return fs.readFileSync(path.resolve(__dirname, 'operation-page-client.tsx'), 'utf8')
}

describe('ingestion operation production layout', () => {
  it('uses the shared product shell and keeps the existing monitor entry', () => {
    const src = readOperationSource()

    expect(src).toContain('data-ingestion-operation-root="true"')
    expect(src).toContain("'flex h-full min-h-0 overflow-y-auto px-3 py-2.5 text-foreground'")
    expect(src).toContain('<PageTitleIcon name="ingestion-operation" className="size-6" />')
    expect(src).toContain('<IngestionViewSwitch compact tone="info" />')
    expect(src).toContain('max-w-[1680px]')
  })

  it('renders one compact composer instead of the old dashboard and task-list stack', () => {
    const src = readOperationSource()

    expect(src).toContain('data-ingestion-operation-workspace="true"')
    expect(src).toContain('data-ingestion-context-panel="true"')
    expect(src).toContain('data-ingestion-pipeline="true"')
    expect(src).toContain('data-ingestion-file-stage="true"')
    expect(src).toContain('data-ingestion-action-bar="true"')
    expect(src).toContain('data-ingestion-advanced-settings="true"')

    expect(src).not.toContain('data-ingestion-control-strip="true"')
    expect(src).not.toContain('data-ingestion-status-rail="true"')
    expect(src).not.toContain('data-ingestion-task-builder="true"')
    expect(src).not.toContain('data-ingestion-task-list-card="true"')
    expect(src).not.toContain('function TaskListCard(')
  })

  it('keeps every real ingestion source and submit path available', () => {
    const src = readOperationSource()

    for (const source of ['local', 'folder', 'url', 'object', 'api']) {
      expect(src).toContain(`value: '${source}'`)
    }
    expect(src).toContain('SourceConfiguration source="folder"')
    expect(src).toContain('SourceConfiguration source="url"')
    expect(src).toContain('SourceConfiguration source="object"')
    expect(src).toContain('SourceConfiguration source="api"')
    expect(src).toContain("uploadFiles(draft.executionMode === 'upload_only' ? 'upload_only' : 'ingest')")
    expect(src).toContain('buildPipeline(draft)')
  })

  it('uses the remaining workspace as a real file staging surface', () => {
    const src = readOperationSource()

    expect(src).toContain("'grid min-h-[calc(100vh-6.5rem)] xl:grid-cols-[300px_minmax(0,1fr)]'")
    expect(src).toContain('className="flex min-h-0 min-w-0 flex-col"')
    expect(src).toContain('data-ingestion-file-staging-workspace="true"')
    expect(src).toContain('data-ingestion-empty-file-drop="true"')
    expect(src).toContain('将文件拖到这里')
    expect(src).toContain('支持 PDF、Word、Markdown、表格、文本与压缩包')
    expect(src).toContain('dragging={dragging}')
    expect(src).toContain('onDragState={setDragging}')
    expect(src).not.toContain('if (!rows.length) return null')
  })
})
