import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('governance common lines source', () => {
  it('uses String.raw when building regex strings with backslashes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')
    const rawMatches = src.match(/String\.raw`/g) ?? []

    expect(rawMatches.length).toBeGreaterThanOrEqual(3)
  })

  it('creates a writable default profile when no custom governance profile exists', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')

    expect(src).toContain("const DEFAULT_COMMON_LINES_PROFILE_KEY = 'common-lines-default'")
    expect(src).toContain("name: '样板行发现默认配置'")
    expect(src).toContain('pipelineApi.createGovernanceProfile(DEFAULT_COMMON_LINES_PROFILE)')
    expect(src).toContain('createErr?.response?.status !== 409')
  })

  it('imports processing script drafts into the selected governance profile instead of uploading documents', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')

    expect(src).toContain("const SCRIPT_UPLOAD_ACCEPT = '.js,.ts,.py,.rs'")
    expect(src).toContain('processing_scripts: nextScripts')
    expect(src).toContain('pipelineApi.updateGovernanceProfile(ref, {')
    expect(src).toContain('导入处理脚本')
    expect(src).toContain('JS/TS、Python、Rust')
    expect(src).toContain('不上传文档，也不会自动执行')
    expect(src).not.toContain('documentApi.uploadBatch')
    expect(src).not.toContain('persist_parsed_content: true')
  })
})
