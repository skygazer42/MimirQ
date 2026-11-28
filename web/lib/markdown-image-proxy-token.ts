import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'node:crypto'

// Production should provide MARKDOWN_IMAGE_PROXY_SECRET so proxy URLs stay opaque end-to-end.
const DEV_FALLBACK_SECRET = 'mimirq-dev-markdown-image-proxy-secret'
const IV_BYTES = 12
const AUTH_TAG_BYTES = 16
const TOKEN_PREFIX = 'v1'
const TOKEN_TTL_MS = 60 * 60 * 1000

function getMarkdownImageProxySecret(): string | null {
  const configured = process.env.MARKDOWN_IMAGE_PROXY_SECRET?.trim()
  if (configured !== undefined && configured !== '') return configured
  return process.env.NODE_ENV === 'production' ? null : DEV_FALLBACK_SECRET
}

function getMarkdownImageProxyKey(): Buffer | null {
  const secret = getMarkdownImageProxySecret()
  if (secret === null) return null
  return createHash('sha256').update(secret).digest()
}

export function mintMarkdownImageProxyToken(rawUrl: string): string | null {
  const key = getMarkdownImageProxyKey()
  if (!key) return null

  const iv = randomBytes(IV_BYTES)
  const cipher = createCipheriv('aes-256-gcm', key, iv, { authTagLength: AUTH_TAG_BYTES })
  const payload = Buffer.from(
    JSON.stringify({
      src: rawUrl,
      exp: Date.now() + TOKEN_TTL_MS,
    }),
    'utf8',
  )
  const ciphertext = Buffer.concat([cipher.update(payload), cipher.final()])
  const authTag = cipher.getAuthTag()
  const tokenBody = Buffer.concat([iv, authTag, ciphertext]).toString('base64url')

  return `${TOKEN_PREFIX}.${tokenBody}`
}

export function resolveMarkdownImageProxyToken(rawToken: string | null | undefined): string | null {
  const token = rawToken?.trim()
  if (token === undefined || token === '') return null

  const [prefix, tokenBody] = token.split('.', 2)
  if (prefix !== TOKEN_PREFIX || !tokenBody) return null

  const key = getMarkdownImageProxyKey()
  if (!key) return null

  try {
    const decoded = Buffer.from(tokenBody, 'base64url')
    if (decoded.length <= IV_BYTES + AUTH_TAG_BYTES) return null

    const iv = decoded.subarray(0, IV_BYTES)
    const authTag = decoded.subarray(IV_BYTES, IV_BYTES + AUTH_TAG_BYTES)
    const ciphertext = decoded.subarray(IV_BYTES + AUTH_TAG_BYTES)

    const decipher = createDecipheriv('aes-256-gcm', key, iv, { authTagLength: AUTH_TAG_BYTES })
    decipher.setAuthTag(authTag)

    const payload = Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString('utf8')
    const parsed: unknown = JSON.parse(payload)
    if (typeof parsed !== 'object' || parsed === null || !('src' in parsed) || !('exp' in parsed)) return null
    const { src, exp } = parsed
    if (typeof src !== 'string' || typeof exp !== 'number' || !Number.isFinite(exp) || exp < Date.now()) {
      return null
    }

    const sourceUrl = src.trim()
    return sourceUrl === '' ? null : sourceUrl
  } catch {
    return null
  }
}
