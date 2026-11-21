import { z } from 'zod'

import { authResponseSchema } from '@/lib/auth-response-schema'
import { readNonEmptyString } from '@/lib/primitive-text'
import { recordSchema } from '@/lib/response-schema'
import type { AuthResponse } from '@/types/backend'

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
  const code = raw?.trim()
  if (code !== undefined && Object.hasOwn(SAML_CALLBACK_ERROR_MESSAGES, code)) {
    return SAML_CALLBACK_ERROR_MESSAGES[code as keyof typeof SAML_CALLBACK_ERROR_MESSAGES]
  }
  return SAML_CALLBACK_ERROR_MESSAGES[SAML_CALLBACK_ERROR_FALLBACK]
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

const samlBridgeResponseSchema = authResponseSchema.extend({ return_to: z.string().optional() })

export async function consumeSamlBridgeState(): Promise<SamlBridgeState | null> {
  try {
    const res = await fetch(SAML_BRIDGE_SESSION_API_PATH, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      cache: 'no-store',
    })
    const payload: unknown = await res.json()

    if (!res.ok) {
      const result = recordSchema.safeParse(payload)
      if (!result.success) return null
      const error = readNonEmptyString(result.data.detail) ?? readNonEmptyString(result.data.error)
      return error ? { kind: 'error', error: getSamlCallbackErrorMessage(error) } : null
    }
    const result = samlBridgeResponseSchema.safeParse(payload)
    if (!result.success) return null
    return {
      kind: 'success',
      session: {
        user: result.data.user,
        token: result.data.token,
      },
      returnTo: readNonEmptyString(result.data.return_to) ?? '/',
    }
  } catch {
    return null
  }
}
