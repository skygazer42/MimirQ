import { describe, expect, it } from 'vitest'

import { UPLOAD_ALLOWED_EXTENSIONS, ZIP_ALLOWED_EXTENSIONS } from './upload-extensions'

describe('upload extensions', () => {
  it('accepts source code files as text-like governance inputs', () => {
    expect(UPLOAD_ALLOWED_EXTENSIONS).toEqual(
      expect.arrayContaining(['.js', '.ts', '.tsx', '.py', '.rs'])
    )
    expect(ZIP_ALLOWED_EXTENSIONS.has('js')).toBe(true)
    expect(ZIP_ALLOWED_EXTENSIONS.has('ts')).toBe(true)
    expect(ZIP_ALLOWED_EXTENSIONS.has('py')).toBe(true)
    expect(ZIP_ALLOWED_EXTENSIONS.has('rs')).toBe(true)
  })
})
