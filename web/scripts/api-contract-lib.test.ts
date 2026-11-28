import { describe, expect, it } from 'vitest'

import {
  extractFrontendRoutesFromFile,
  listFrontendSourceFiles,
  parseBackendModuleImports,
  parseBackendRoutes,
  parseFrontendRoutes,
} from './api-contract-lib.mjs'

describe('API contract route extraction', () => {
  it('resolves qualified, multiline and renamed imports from their actual declarations', () => {
    const imports = parseBackendModuleImports(
      `
      import app.api.v1.knowledge_graph.routes as graph
      from app.api.v1 import (
        documents,
        health as status,
      )
    `,
      'app/api/v1/__init__.py',
    )
    expect(imports.get('graph')).toBe('app/api/v1/knowledge_graph/routes')
    expect(imports.get('documents')).toBe('app/api/v1/documents')
    expect(imports.get('status')).toBe('app/api/v1/health')
  })

  it('resolves relative imports in the declaring module package', () => {
    const imports = parseBackendModuleImports(
      'from . import extraction as child\nfrom .. import health as status',
      'app/api/v1/knowledge_graph/routes.py',
    )
    expect(imports.get('child')).toBe('app/api/v1/knowledge_graph/extraction')
    expect(imports.get('status')).toBe('app/api/v1/health')
  })

  it('exposes unreadable declared frontend input instead of treating it as no routes', () => {
    expect(() => parseFrontendRoutes({ files: ['web/lib/api/no-such-contract-input.ts'] })).toThrow()
  })
  it('finds routes through actual registered aliases and nested document modules', () => {
    const routes = parseBackendRoutes()
    expect(routes.has('GET /kg/graph')).toBe(true)
    expect(routes.has('POST /kg/imports/preview')).toBe(true)
    expect(routes.has('POST /documents/chunk-preview')).toBe(true)
  })
  it('finds API client modules with the paths used by the coverage checker', () => {
    const contractFiles = listFrontendSourceFiles().filter((file) => file.startsWith('web/lib/api/'))

    expect(contractFiles).toContain('web/lib/api/chat.ts')
    expect(parseFrontendRoutes({ files: contractFiles })).toContainEqual({
      method: 'POST',
      path: '/chat/stream',
      src: 'web/lib/api/chat.ts',
    })
  })

  it('recognizes routes called through authenticatedFetch', () => {
    expect(extractFrontendRoutesFromFile('web/lib/api/chat.ts')).toContainEqual({
      method: 'POST',
      path: '/chat/stream',
      src: 'web/lib/api/chat.ts',
    })
  })

  it('recognizes an Axios call with a response type argument', () => {
    expect(extractFrontendRoutesFromFile('web/lib/api/auth.ts')).toContainEqual({
      method: 'POST',
      path: '/auth/login',
      src: 'web/lib/api/auth.ts',
    })
  })
})
