import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph service source', () => {
  it('uses structuredClone instead of JSON stringify/parse deep copies', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-service.ts'), 'utf8')

    expect(src).toContain('structuredClone(')
    expect(src).not.toContain('JSON.parse(JSON.stringify')
  })

  it('uses codePointAt for unicode-safe hashing', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-service.ts'), 'utf8')

    expect(src).toContain('codePointAt(')
    expect(src).not.toContain('charCodeAt(')
  })

  it('ships a multi-cluster 3D-ready sample graph for the unscoped graph page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-service.ts'), 'utf8')

    expect(src).toContain("createNode('ai', 'Artificial Intelligence', 'concept', 34)")
    expect(src).toContain("createNode('nlp', 'NLP', 'technology', 23)")
    expect(src).toContain("createNode('computer-vision', 'Computer Vision', 'technology', 23)")
    expect(src).toContain("createNode('deep-learning', 'Deep Learning', 'model', 24)")
    expect(src).toContain("createNode('reinforcement-learning', 'Reinforcement Learning', 'application', 22)")
    expect(src).toContain("label: '概念 / Concept'")
    expect(src).toContain("label: '技术 / Technology'")
    expect(src).toContain("createLink('ai', 'machine-learning', '子领域'")
    expect(src).toContain("createLink('nlp', 'named-entity-recognition', '应用于'")
  })
})
