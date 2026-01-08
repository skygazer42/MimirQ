/**
 * Backend API response type aliases (generated OpenAPI types).
 */
import type { paths } from './openapi'

export type HealthResponse = paths['/api/v1/health']['get']['responses'][200]['content']['application/json']
export type ReadyResponse = paths['/api/v1/health/ready']['get']['responses'][200]['content']['application/json']
export type MetaResponse = paths['/api/v1/meta']['get']['responses'][200]['content']['application/json']
