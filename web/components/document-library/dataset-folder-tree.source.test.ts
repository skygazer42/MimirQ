import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset folder tree source', () => {
  it('moves container copy into the DatasetFolderTree catalog while keeping view fallbacks', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'dataset-folder-tree.tsx'), 'utf8')

    expect(src).toContain("useTranslations('DatasetFolderTree')")
    expect(src).toContain("collapse: t('collapse')")
    expect(src).toContain("allDirectories: '全部目录'")
    expect(src).toContain("t('emptyWithPath')")
  })
})
