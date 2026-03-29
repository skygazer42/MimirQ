import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const openapiRequestMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/openapi-request', () => ({
  createOpenApiAxiosClient: () => openapiRequestMock,
}))

let pipelineApi: typeof import('./api-client').pipelineApi
let openapiSpec: any
const OPENAPI_EXPORT_TIMEOUT_MS = 300_000

function loadOpenApiSpec() {
  const specPath = path.join(os.tmpdir(), `mimirq-openapi-${process.pid}.json`)
  if (!fs.existsSync(specPath)) {
    const result = spawnSync('node', ['scripts/export-openapi.mjs', '--out', specPath], {
      cwd: path.resolve(__dirname, '..'),
      encoding: 'utf8',
      timeout: OPENAPI_EXPORT_TIMEOUT_MS,
    })
    if (result.status !== 0) {
      throw new Error(result.stderr || result.stdout || 'failed to export openapi spec')
    }
  }

  return JSON.parse(fs.readFileSync(specPath, 'utf8'))
}

describe('pipelineApi.governanceProfiles', () => {
  beforeAll(async () => {
    ;({ pipelineApi } = await import('./api-client'))
    openapiSpec = loadOpenApiSpec()
  }, OPENAPI_EXPORT_TIMEOUT_MS)

  beforeEach(() => {
    openapiRequestMock.mockReset()
  })

  it('exposes resolved profile endpoint client', () => {
    expect(typeof (pipelineApi as any).getGovernanceProfileResolved).toBe('function')
  })

  it('normalizes outgoing regex rules to satisfy the backend openapi contract', async () => {
    const regexRuleSchema = openapiSpec.components.schemas.RegexRuleModel
    expect(regexRuleSchema?.required).toEqual(expect.arrayContaining(['pattern']))
    expect(regexRuleSchema?.properties?.repl?.default).toBe('')
    expect(regexRuleSchema?.properties?.flags?.default).toBe(0)

    openapiRequestMock.mockResolvedValueOnce({
      id: null,
      key: 'demo',
      name: 'Demo',
      payload: {
        version: '1',
        extends: null,
        input_formats: ['markdown'],
        pipeline_patch: {},
        regex_rules: [],
      },
    })

    await pipelineApi.createGovernanceProfile({
      name: 'Demo',
      payload: {
        version: '1',
        input_formats: ['markdown'],
        pipeline_patch: {},
        regex_rules: [{ pattern: 'foo' }],
      },
    } as any)

    expect(openapiRequestMock).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.objectContaining({
          payload: expect.objectContaining({
            regex_rules: [{ pattern: 'foo', repl: '', flags: 0 }],
          }),
        }),
      })
    )
  })

  it('normalizes incoming profile payloads so they still match the backend openapi shape', async () => {
    const payloadSchema = openapiSpec.components.schemas.GovernanceProfilePayload
    const regexRuleSchema = openapiSpec.components.schemas.RegexRuleModel

    expect(payloadSchema?.properties?.input_formats?.items?.enum).toEqual(
      expect.arrayContaining(['markdown', 'html'])
    )
    expect(regexRuleSchema?.properties?.flags?.type).toBe('integer')

    openapiRequestMock.mockResolvedValueOnce({
      id: null,
      key: 'demo',
      name: 'Demo',
      payload: {
        version: null,
        extends: undefined,
        input_formats: [],
        pipeline_patch: null,
        regex_rules: [{ pattern: 'foo' }],
      },
    })

    const profile = await pipelineApi.getGovernanceProfile('demo')

    expect(profile.payload.version).toBe('1')
    expect(profile.payload.extends).toBeNull()
    expect(profile.payload.input_formats).toEqual(['markdown'])
    expect(profile.payload.pipeline_patch).toEqual({})
    expect(profile.payload.regex_rules).toEqual([{ pattern: 'foo', repl: '', flags: 0 }])
    expect(profile.payload.input_formats.every((value) => ['markdown', 'html'].includes(value))).toBe(true)
  })
})
