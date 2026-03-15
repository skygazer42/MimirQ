function bytesToBase64(bytes: Uint8Array): string {
  // Prefer Buffer when available (Node), otherwise fall back to btoa (browser).
  if (typeof Buffer !== 'undefined') {
    return Buffer.from(bytes).toString('base64')
  }

  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  // btoa expects Latin-1 bytes, which we provide via String.fromCharCode.
  return btoa(binary)
}

function base64ToBytes(base64: string): Uint8Array {
  if (typeof Buffer !== 'undefined') {
    return Uint8Array.from(Buffer.from(base64, 'base64'))
  }

  const binary = atob(base64)
  const out = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    out[i] = binary.charCodeAt(i)
  }
  return out
}

export function base64UrlEncode(bytes: Uint8Array): string {
  return bytesToBase64(bytes).replaceAll(/\+/g, '-').replaceAll(/\//g, '_').replaceAll(/=+$/g, '')
}

export function base64UrlDecodeToBytes(base64Url: string): Uint8Array {
  const raw = String(base64Url || '').trim()
  if (!raw) return new Uint8Array()

  let base64 = raw.replaceAll(/-/g, '+').replaceAll(/_/g, '/')
  const pad = base64.length % 4
  if (pad) base64 += '='.repeat(4 - pad)

  return base64ToBytes(base64)
}

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

  const data = new TextEncoder().encode(String(input || ''))
  const digest = await globalThis.crypto.subtle.digest('SHA-256', data)
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

