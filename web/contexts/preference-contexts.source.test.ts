import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('preference contexts', () => {
  it('memoizes provider values and uses standard useState setter naming', () => {
    const parserSrc = fs.readFileSync(path.resolve(__dirname, 'parser-backend-context.tsx'), 'utf8')
    const chunkSrc = fs.readFileSync(path.resolve(__dirname, 'chunk-strategy-context.tsx'), 'utf8')

    expect(parserSrc).toContain('const [parserBackend, setParserBackend] = useState(')
    expect(parserSrc).toContain('const contextValue = useMemo(() => ({')
    expect(chunkSrc).toContain('const [chunkStrategy, setChunkStrategy] = useState(')
    expect(chunkSrc).toContain('const contextValue = useMemo(() => ({')
  })

  it('shares the masking-mode normalization helper in pipeline options context', () => {
    const pipelineSrc = fs.readFileSync(path.resolve(__dirname, 'pipeline-options-context.tsx'), 'utf8')

    expect(pipelineSrc).toContain('const normalizeMaskingMode =')
    expect(pipelineSrc).toContain('governance_pii_mode: normalizeMaskingMode(')
    expect(pipelineSrc).toContain('governance_secrets_mode: normalizeMaskingMode(')
  })

  it('does not disable KG when pipeline overrides are enabled by default', () => {
    const pipelineSrc = fs.readFileSync(path.resolve(__dirname, 'pipeline-options-context.tsx'), 'utf8')

    expect(pipelineSrc).toContain('kg_enabled: true,')
    expect(pipelineSrc).toContain('event_vector_enabled: true,')
    expect(pipelineSrc).toContain('entity_vector_enabled: true,')
  })
})
