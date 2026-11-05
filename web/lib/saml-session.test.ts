import { afterEach, describe, expect, it, vi } from 'vitest'

import { consumeSamlBridgeState, getSamlCallbackErrorMessage } from './saml-session'

describe('getSamlCallbackErrorMessage', () => {
  it.each(['debug stack trace', 'toString', 'constructor', '__proto__'])(
    'falls back for the unknown error %s',
    (error) => {
      expect(getSamlCallbackErrorMessage(error)).toBe('SAML sign-in failed. Please try again.')
    },
  )
})

describe('consumeSamlBridgeState', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not echo arbitrary backend error detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ detail: 'backend stack trace' }, { status: 500 })))

    await expect(consumeSamlBridgeState()).resolves.toEqual({
      kind: 'error',
      error: 'SAML sign-in failed. Please try again.',
    })
  })
})
