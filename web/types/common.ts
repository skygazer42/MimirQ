/**
 * Common/shared types re-exported by `@/types`.
 */

import type { OpenApiSchema } from './backend'

export type PermissionEnum = OpenApiSchema<'DatasetPermissionEnum'>
export type DocumentAccessMode = OpenApiSchema<'DocumentAccessInfo'>['mode']
export type JsonObject = Record<string, unknown>
