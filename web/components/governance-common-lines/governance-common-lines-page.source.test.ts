import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('governance common lines source', () => {
  it('uses String.raw when building regex strings with backslashes', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'governance-common-lines-page.tsx'),
      'utf8'
    )
    const rawMatches = src.match(/String\.raw`/g) ?? []

    expect(rawMatches.length).toBeGreaterThanOrEqual(3)
  })

  it('creates a writable default profile when no custom governance profile exists', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'governance-common-lines-page.tsx'),
      'utf8'
    )

    expectSourceToContain(
      src,
      "const DEFAULT_COMMON_LINES_PROFILE_KEY = 'common-lines-default'"
    )
    expectSourceToContain(src, "name: '重复内容治理默认配置'")
    expectSourceToContain(
      src,
      'pipelineApi.createGovernanceProfile(DEFAULT_COMMON_LINES_PROFILE)'
    )
    expectSourceToContain(src, 'createErr?.response?.status !== 409')
  })

  it('imports processing script drafts into the selected governance profile instead of uploading documents', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'governance-common-lines-page.tsx'),
      'utf8'
    )

    expectSourceToContain(src, "const SCRIPT_UPLOAD_ACCEPT = '.js,.ts,.py,.rs'")
    expectSourceToContain(src, 'processing_scripts: nextScripts')
    expectSourceToContain(src, 'pipelineApi.updateGovernanceProfile(ref, {')
    expectSourceToContain(src, '导入处理脚本')
    expectSourceToContain(src, 'JS/TS、Python、Rust')
    expectSourceToContain(src, '不上传文档，也不会自动执行')
    expectSourceNotToContain(src, 'documentApi.uploadBatch')
    expectSourceNotToContain(src, 'persist_parsed_content: true')
  })

  it('loads dataset and governance profile metadata through TanStack Query', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'governance-common-lines-page.tsx'),
      'utf8'
    )

    expectSourceToContain(src, "from '@tanstack/react-query'")
    expectSourceToContain(src, 'useQuery')
    expectSourceToContain(src, 'useQueryClient')
    expectSourceToContain(src, 'queryKey: queryKeys.datasets.list')
    expectSourceToContain(src, 'queryKey: queryKeys.governance.profiles')
    expectSourceToContain(src, 'queryClient.invalidateQueries')
    expectSourceNotToContain(src, 'const [datasets, setDatasets]')
    expectSourceNotToContain(src, 'const [profiles, setProfiles]')
    expectSourceNotToContain(src, 'setLoadingMeta')
    expectSourceNotToContain(src, 'detachPromise(loadMeta())')
  })
})
