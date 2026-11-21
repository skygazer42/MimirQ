import type { MetaDetailsResponse, MetaResponse } from '@/types/backend'

import { openapiRequest, type ApiRequestOptions } from '@/lib/api/core'

export type BackendMeta = MetaResponse
export type BackendMetaDetails = MetaDetailsResponse

export const metaApi = {
  get(options?: ApiRequestOptions): Promise<BackendMeta> {
    return openapiRequest({ path: '/api/v1/meta', method: 'get', signal: options?.signal })
  },

  details(options?: ApiRequestOptions): Promise<BackendMetaDetails> {
    return openapiRequest({ path: '/api/v1/meta/details', method: 'get', signal: options?.signal })
  },
}
