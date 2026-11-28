import { createServer } from 'node:http'

import next from 'next'

import { sanitizeForwardedHeaders } from './trusted-forwarding.mjs'

const defaultHostname = process.argv.includes('--public') ? '0.0.0.0' : '127.0.0.1'
const configuredHostname = process.env.HOST?.trim()
const hostname = configuredHostname === undefined || configuredHostname === '' ? defaultHostname : configuredHostname
const configuredPort = process.env.PORT
const portText = configuredPort === undefined || configuredPort === '' ? '3000' : configuredPort.trim()
const port = Number(portText)
if (!/^\+?\d+$/.test(portText) || port < 1 || port > 65535) {
  throw new Error('PORT must be an integer between 1 and 65535')
}
if (!process.env.MARKDOWN_IMAGE_PROXY_SECRET?.trim()) {
  throw new Error('MARKDOWN_IMAGE_PROXY_SECRET is required in production')
}

const app = next({ dev: false, hostname, port })
await app.prepare()

const handle = app.getRequestHandler()
const handleUpgrade = app.getUpgradeHandler()
const server = createServer((request, response) => {
  sanitizeForwardedHeaders(request.headers, request.socket.remoteAddress)
  handle(request, response).catch((error) => {
    console.error('[production-server] Request failed', error)
    if (!response.headersSent) response.writeHead(500)
    response.end('Internal Server Error')
  })
})

server.on('upgrade', (request, socket, head) => {
  sanitizeForwardedHeaders(request.headers, request.socket.remoteAddress)
  handleUpgrade(request, socket, head)
})

server.listen(port, hostname, () => {
  console.log(`[production-server] Listening on http://${hostname}:${port}`)
})

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    server.close(() => process.exit(0))
  })
}
