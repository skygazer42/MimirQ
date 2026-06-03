import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings object storage section', () => {
  it('exposes MinIO settings through the settings page and state hook', () => {
    const section = fs.readFileSync(
      path.resolve(__dirname, './_sections/object-storage-section.tsx'),
      'utf8'
    )
    const page = fs.readFileSync(path.resolve(__dirname, './page.tsx'), 'utf8')
    const state = fs.readFileSync(path.resolve(__dirname, './use-settings-page-state.ts'), 'utf8')
    const api = fs.readFileSync(path.resolve(__dirname, '../../lib/api/settings.ts'), 'utf8')

    expect(api).toContain('export interface MinIOConfig')
    expect(api).toContain('minio: MinIOConfig')
    expect(state).toContain('const DEFAULT_MINIO: MinIOConfig')
    expect(state).toContain('minioMerged')
    expect(state).toContain('updateMinIO')
    expect(page).toContain("import { ObjectStorageSection } from './_sections/object-storage-section'")
    expect(page).toContain("{ id: 'sec-storage', label: '对象存储'")
    expect(page).toContain('minio={state.minioMerged}')
    expect(page).toContain('updateMinIO={state.updateMinIO}')
    expect(section).toContain('MinIO')
    expect(section).toContain('对象存储开关')
    expect(section).toContain('documents_enabled')
    expect(section).toContain('image_max_bytes')
  })
})
