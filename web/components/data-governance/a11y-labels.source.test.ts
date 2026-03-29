import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('data governance accessibility labels', () => {
  it('gives icon-only classifier and annotator controls contextual accessible names', () => {
    const classifierSrc = fs.readFileSync(path.resolve(__dirname, 'data-classifier.tsx'), 'utf8')
    const annotatorSrc = fs.readFileSync(path.resolve(__dirname, 'data-annotator.tsx'), 'utf8')

    expect(classifierSrc).toContain('aria-label={`移除标签 ${tag}`}')
    expect(classifierSrc).toContain("aria-label={newTag ? `添加标签 ${newTag}` : '添加标签'}")
    expect(annotatorSrc).toContain('aria-label={`删除 ${type.label} 标注 ${anno.start}-${anno.end}`}')
  })
})
