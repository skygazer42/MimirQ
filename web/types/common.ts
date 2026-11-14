/**
 * Common/shared types re-exported by `@/types`.
 */

import type { OpenApiSchema } from './backend'

export type PermissionEnum = OpenApiSchema<'DatasetPermissionEnum'>
export type DocumentAccessMode = 'inherit' | PermissionEnum
export type LooseString<T extends string> = T | (string & {})
export type JsonObject = Record<string, unknown>
