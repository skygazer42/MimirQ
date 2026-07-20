import type { IncomingHttpHeaders } from 'node:http'

export function sanitizeForwardedHeaders(
  headers: IncomingHttpHeaders,
  remoteAddress: string | undefined,
): void
