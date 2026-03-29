import type { MetaResponse } from '@/types/backend'

import { openapiRequest } from '@/lib/api/core'

export type BackendMeta = MetaResponse

export const metaApi = {
  async get(): Promise<BackendMeta> {
    return openapiRequest({ path: '/api/v1/meta', method: 'get' })
  },
}
