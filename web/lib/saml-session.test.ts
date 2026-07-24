import { afterEach, describe, expect, it, vi } from 'vitest'

import { consumeSamlBridgeState, getSamlCallbackErrorMessage } from './saml-session'

describe('getSamlCallbackErrorMessage', () => {
  it('falls back for unknown error values', () => {
    expect(getSamlCallbackErrorMessage('debug stack trace')).toBe('SAML sign-in failed. Please try again.')
  })
})

describe('consumeSamlBridgeState', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not echo arbitrary backend error detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        Response.json(
          { detail: 'backend stack trace' },
          { status: 500 }
        )
      )
    )

    await expect(consumeSamlBridgeState()).resolves.toEqual({
      kind: 'error',
      error: 'SAML sign-in failed. Please try again.',
    })
  })
})
