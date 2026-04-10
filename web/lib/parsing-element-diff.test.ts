import { describe, expect, it } from 'vitest'

import { diffParsingElements } from './parsing-element-diff'

describe('parsing-element-diff', () => {
  it('summarizes added and removed specialty elements by kind', () => {
    const diff = diffParsingElements(
      [
        { id: 'seal-a', kind: 'seal', page: 2, text: '杭州测试科技有限公司' },
        { id: 'eq-a', kind: 'equation', page: 1, text: 'E = mc^2' },
      ],
      [
        { id: 'seal-b', kind: 'seal', page: 2, text: '财务专用章' },
        { id: 'eq-a', kind: 'equation', page: 1, text: 'E = mc^2' },
        { id: 'img-a', kind: 'image', page: 1, text: 'chart preview' },
      ]
    )

    expect(diff.addedByKind.seal).toBe(1)
    expect(diff.removedByKind.seal).toBe(1)
    expect(diff.addedByKind.image).toBe(1)
    expect(diff.addedSealTexts).toContain('财务专用章')
    expect(diff.removedSealTexts).toContain('杭州测试科技有限公司')
  })
})
