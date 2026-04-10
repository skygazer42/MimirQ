import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('parsing api source', () => {
  it('exposes normalized elements in the runtime parsing response contract', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing.ts'), 'utf8')

    expect(src).toContain('export interface ParsingElement')
    expect(src).toContain('pages?: number[] | null')
    expect(src).toContain('elements?: ParsingElement[] | null')
    expect(src).toContain('const parsingElementSchema = z')
    expect(src).toContain('pages: z.array(z.number().int()).nullable().optional()')
    expect(src).toContain('elements: z.array(parsingElementSchema).nullable().optional()')
  })

  it('defines extraction request and response contracts for parsing fields', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing.ts'), 'utf8')

    expect(src).toContain('export interface ParsingExtractRequest')
    expect(src).toContain('export interface ParsingExtractResponse')
    expect(src).toContain("kind?: ParsingElement['kind'] | null")
    expect(src).toContain('const parsingExtractFieldSpecSchema = z')
    expect(src).toContain('const parsingElementKindSchema = z.enum(')
    expect(src).toContain('kind: parsingElementKindSchema.nullable().optional()')
    expect(src).toContain('const parsingExtractResponseSchema = z')
    expect(src).toContain("path: '/api/v1/parsing/documents/{document_id}/extract'")
  })
})
