/**
 * Replace client-controlled forwarding identity with the direct TCP peer before
 * Next.js applies rewrites. The backend may trust this proxy, not browser input.
 *
 * @param {import('node:http').IncomingHttpHeaders} headers
 * @param {string | undefined} remoteAddress
 */
export function sanitizeForwardedHeaders(headers, remoteAddress) {
  const address = remoteAddress?.trim().replace(/^::ffff:/i, '')

  for (const name of ['x-forwarded-host', 'x-forwarded-port', 'x-forwarded-proto', 'x-real-ip']) {
    delete headers[name]
  }
  if (address === undefined || address === '') {
    delete headers['x-forwarded-for']
    return
  }
  headers['x-forwarded-for'] = address
}
