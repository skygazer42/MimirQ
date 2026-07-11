import type { MetaDetailsResponse, MetaResponse } from '@/types/backend'

import { openapiRequest } from '@/lib/api/core'

export type BackendMeta = MetaResponse
export type BackendMetaDetails = MetaDetailsResponse

export const metaApi = {
  async get(): Promise<BackendMeta> {
    return openapiRequest({ path: '/api/v1/meta', method: 'get' })
  },

  async details(): Promise<BackendMetaDetails> {
    return openapiRequest({ path: '/api/v1/meta/details', method: 'get' })
  },
}
