import type { AuthResponse } from '@/types'

export const SAML_BRIDGE_COOKIE_NAME = 'mimirq_saml_bridge'
export const SAML_BRIDGE_COOKIE_PATH = '/api/saml'
export const SAML_BRIDGE_SESSION_API_PATH = '/api/saml/session'
export const SAML_CALLBACK_ERROR_FALLBACK = 'saml_sign_in_failed'

export const SAML_CALLBACK_ERROR_MESSAGES = {
  saml_access_denied: 'Your account is not allowed to sign in with this identity provider.',
  saml_backend_unreachable: 'The sign-in service is temporarily unavailable. Please try again.',
  saml_invalid_request: 'The sign-in request was invalid. Please start again from the login page.',
  saml_invalid_response: 'The identity provider returned an invalid SAML response.',
  saml_invalid_session: 'Your SAML sign-in session was invalid. Please try again.',
  saml_missing_response: 'The identity provider did not return a SAML response.',
  [SAML_CALLBACK_ERROR_FALLBACK]: 'SAML sign-in failed. Please try again.',
} as const

export function getSamlCallbackErrorMessage(raw: string | null | undefined): string {
  const value = String(raw || '').trim()
  if (!value) {
    return SAML_CALLBACK_ERROR_MESSAGES[SAML_CALLBACK_ERROR_FALLBACK]
  }
  return SAML_CALLBACK_ERROR_MESSAGES[value as keyof typeof SAML_CALLBACK_ERROR_MESSAGES]
    || SAML_CALLBACK_ERROR_MESSAGES[SAML_CALLBACK_ERROR_FALLBACK]
}

export type SamlBridgeState =
  | {
      kind: 'success'
      session: AuthResponse
      returnTo: string
    }
  | {
      kind: 'error'
      error: string
    }

type SamlBridgeResponse = AuthResponse & {
  return_to?: string
  error?: string
  detail?: string
}

export async function consumeSamlBridgeState(): Promise<SamlBridgeState | null> {
  try {
    const res = await fetch(SAML_BRIDGE_SESSION_API_PATH, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      cache: 'no-store',
    })
    const payload = (await res.json().catch(() => null)) as SamlBridgeResponse | null

    if (!res.ok) {
      const error = String(payload?.detail || payload?.error || '').trim()
      return error ? { kind: 'error', error: getSamlCallbackErrorMessage(error) } : null
    }
    if (!payload?.user || !payload?.token?.access_token) {
      return null
    }
    return {
      kind: 'success',
      session: {
        user: payload.user,
        token: payload.token,
      },
      returnTo: String(payload.return_to || '/').trim() || '/',
    }
  } catch {
    return null
  }
}
