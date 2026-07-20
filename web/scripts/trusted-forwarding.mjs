/**
 * Replace client-controlled forwarding identity with the direct TCP peer before
 * Next.js applies rewrites. The backend may trust this proxy, not browser input.
 *
 * @param {import('node:http').IncomingHttpHeaders} headers
 * @param {string | undefined} remoteAddress
 */
export function sanitizeForwardedHeaders(headers, remoteAddress) {
  const rawAddress = String(remoteAddress || '').trim()
  const address = rawAddress.toLowerCase().startsWith('::ffff:') ? rawAddress.slice(7) : rawAddress

  for (const name of [
    'x-forwarded-host',
    'x-forwarded-port',
    'x-forwarded-proto',
    'x-real-ip',
  ]) {
    delete headers[name]
  }
  if (address) {
    headers['x-forwarded-for'] = address
  } else {
    delete headers['x-forwarded-for']
  }
}
