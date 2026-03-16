import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  consumeSamlBridgeState,
  encodeSamlBridgeState,
  SAML_BRIDGE_COOKIE_NAME,
} from '@/lib/saml-session'

describe('saml-session', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('encodes bridge state as unpadded base64url', () => {
    vi.stubGlobal('Buffer', undefined)
    const encoded = encodeSamlBridgeState({ kind: 'error', error: 'x' })

    expect(encoded).toBe('eyJraW5kIjoiZXJyb3IiLCJlcnJvciI6IngifQ')
    expect(encoded).not.toContain('=')
  })

  it('consumes bridge state from the cookie and clears it', () => {
    vi.stubGlobal('Buffer', undefined)
    const documentStub = { cookie: '' }
    const payload = { kind: 'error' as const, error: 'Invalid signature' }
    const encoded = encodeSamlBridgeState(payload)

    documentStub.cookie = `${SAML_BRIDGE_COOKIE_NAME}=${encodeURIComponent(encoded)}`
    vi.stubGlobal('document', documentStub)

    expect(consumeSamlBridgeState()).toEqual(payload)
    expect(documentStub.cookie).toContain('Max-Age=0')
  })
})
