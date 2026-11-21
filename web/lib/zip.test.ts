// @vitest-environment happy-dom

import JSZip from 'jszip'
import { describe, expect, it } from 'vitest'

import { extractZipFiles, isZipFile } from './zip'

describe('ZIP source files', () => {
  it('reads actual bytes, normalizes paths and omits folders and system artifacts', async () => {
    const archive = new JSZip()
    archive.file('folder/report.md', '# Report')
    archive.file('windows\\empty.txt', '')
    archive.file('__MACOSX/resource', 'metadata')
    archive.file('folder/.DS_Store', 'metadata')
    archive.folder('empty-folder')
    const buffer = await archive.generateAsync({ type: 'arraybuffer' })

    const files = await extractZipFiles(new File([buffer], 'reports.zip', { type: 'application/zip' }))

    expect(files.map((entry) => entry.path)).toEqual(['folder/report.md', 'windows/empty.txt'])
    expect(files.map((entry) => entry.file.name)).toEqual(['report.md', 'empty.txt'])
    expect(await files[0].file.text()).toBe('# Report')
    expect(files[1].file.size).toBe(0)
  })

  it('rejects an unreadable archive instead of returning an empty result', async () => {
    await expect(extractZipFiles(new File(['not ZIP bytes'], 'broken.zip'))).rejects.toThrow()
  })

  it('recognizes either a ZIP filename or the declared ZIP MIME type', () => {
    expect(isZipFile(new File([], 'ARCHIVE.ZIP'))).toBe(true)
    expect(isZipFile(new File([], 'archive', { type: 'application/zip' }))).toBe(true)
    expect(isZipFile(new File([], 'report.md', { type: 'text/markdown' }))).toBe(false)
  })
})
