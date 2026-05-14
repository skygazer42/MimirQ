import { describe, expect, it } from 'vitest'

import { parseBackendRoutes } from './api-contract-lib.mjs'

describe('api contract backend route parser', () => {
  it('includes routes from routers nested under a top-level API module', () => {
    const routes = parseBackendRoutes()

    expect(routes.get('GET /connectors')).toBe('app/api/v1/connectors_catalog.py')
    expect(routes.get('GET /chat/conversations/{}/summary')).toBe('app/api/v1/chat_conversation_memory.py')
    expect(routes.get('POST /chat/conversations/{}/summary/update')).toBe('app/api/v1/chat_conversation_memory.py')
    expect(routes.get('DELETE /chat/conversations/{}/summary')).toBe('app/api/v1/chat_conversation_memory.py')
    expect(routes.get('GET /chat/conversations/{}/checkpoints')).toBe('app/api/v1/chat_conversation_memory.py')
    expect(routes.get('GET /chat/conversations/{}/checkpoints/{}')).toBe('app/api/v1/chat_conversation_memory.py')
    expect(routes.get('DELETE /chat/conversations/{}/checkpoints')).toBe('app/api/v1/chat_conversation_memory.py')
  })

  it('includes nested router prefixes declared on child APIRouters', () => {
    const routes = parseBackendRoutes()

    expect(routes.get('GET /documents/dead-letters')).toBe('app/api/v1/document_dead_letters.py')
    expect(routes.get('POST /documents/dead-letters/{}/replay')).toBe('app/api/v1/document_dead_letters.py')
  })
})
