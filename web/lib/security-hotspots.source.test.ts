import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('security hotspot source guards', () => {
  it('avoids hotspot-prone regexes in env helpers', () => {
    const src = read('./env.ts')

    expect(src).not.toContain(".replace(/\\/+$/, '')")
    expect(src).not.toContain(".replace(/=+$/")
    expect(src).not.toContain('/^https?:\\/\\//i.test(path)')
  })

  it('avoids Math.random fallbacks in request and local parsed file ids', () => {
    expect(read('./request-id.ts')).not.toContain('Math.random(')
    expect(read('../hooks/use-parsed-files.ts')).not.toContain('Math.random(')
  })

  it('avoids Math.random in graph mock expansion', () => {
    expect(read('../services/graph-service.ts')).not.toContain('Math.random(')
  })

  it('runs the dev container as a non-root user and hardens copied files after staging', () => {
    const devDockerfile = read('../Dockerfile')
    const prodDockerfile = read('../Dockerfile.prod')

    expect(devDockerfile).toContain('USER node')
    expect(devDockerfile).toContain('RUN chown -R node:node /app')
    expect(devDockerfile).not.toContain('COPY --chown=node:node app ./app')

    expect(prodDockerfile).toContain('RUN chown -R node:node /app')
    expect(prodDockerfile).toContain('chmod -R a-w /app/package.json /app/next.config.mjs /app/public /app/.next_build /app/node_modules')
    expect(prodDockerfile).not.toContain('--chmod=')
  })
})
