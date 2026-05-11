import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('KnowledgeDocumentsPanel single delete confirmation', () => {
  it('confirms single delete via AlertDialog and keeps errors next to the action', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-documents-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'singleDeleteDoc')
    expectSourceToContain(src, 'formatApiError')
    expectSourceToContain(src, 'setSingleDeleteError')
    expectSourceToContain(src, 'toast.success(t("toasts.deleteSuccess"))')
    expectSourceToContain(src, 'Delete document failed:')
  })
})
