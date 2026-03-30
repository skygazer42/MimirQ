import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('data governance accessibility labels', () => {
  it('gives icon-only classifier and annotator controls contextual accessible names', () => {
    const classifierSrc = fs.readFileSync(path.resolve(__dirname, 'data-classifier.tsx'), 'utf8')
    const annotatorSrc = fs.readFileSync(path.resolve(__dirname, 'data-annotator.tsx'), 'utf8')

    expect(classifierSrc).toContain("aria-label={t('a11y.removeTagWithValue', { tag })}")
    expect(classifierSrc).toContain("aria-label={newTag ? t('a11y.addTagWithValue', { tag: newTag }) : t('a11y.addTag')}")
    expect(annotatorSrc).toContain("aria-label={t('a11y.deleteAnnotation', {")
  })
})
