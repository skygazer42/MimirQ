import { base64UrlDecodeToBytes, base64UrlEncode, encodeUtf8 } from '@/lib/encoding'

export { base64UrlDecodeToBytes, base64UrlEncode } from '@/lib/encoding'

export function randomBytes(byteLength: number): Uint8Array {
  if (!Number.isFinite(byteLength) || byteLength <= 0) {
    throw new Error('invalid_byte_length')
  }
  if (!globalThis.crypto?.getRandomValues) {
    throw new Error('crypto_unavailable')
  }

  const out = new Uint8Array(byteLength)
  globalThis.crypto.getRandomValues(out)
  return out
}

export function generateOauthState(): string {
  // 16 bytes => 22 chars (unpadded) base64url, plenty for CSRF state.
  return base64UrlEncode(randomBytes(16))
}

export function generatePkceCodeVerifier(): string {
  // PKCE verifier must be 43-128 chars using unreserved characters.
  // 32 bytes => 43 chars (unpadded) base64url.
  return base64UrlEncode(randomBytes(32))
}

export async function sha256Bytes(input: string): Promise<Uint8Array> {
  if (!globalThis.crypto?.subtle) {
    throw new Error('crypto_subtle_unavailable')
  }

  const data = encodeUtf8(String(input || ''))
  const digest = await globalThis.crypto.subtle.digest('SHA-256', data as BufferSource)
  return new Uint8Array(digest)
}

export async function pkceChallengeFromVerifier(verifier: string): Promise<string> {
  const digest = await sha256Bytes(verifier)
  return base64UrlEncode(digest)
}

export function decodeJwtPayload<T = unknown>(token: string): T {
  const raw = String(token || '').trim()
  const parts = raw.split('.')
  if (parts.length < 2) {
    throw new Error('invalid_jwt')
  }

  const payloadBytes = base64UrlDecodeToBytes(parts[1])
  const json = new TextDecoder().decode(payloadBytes)
  return JSON.parse(json) as T
}

export function tryDecodeJwtPayload<T = unknown>(token: string): T | null {
  try {
    return decodeJwtPayload<T>(token)
  } catch {
    return null
  }
}
