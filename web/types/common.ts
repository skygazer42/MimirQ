/**
 * Common/shared types re-exported by `@/types`.
 */

export type PermissionEnum = 'only_me' | 'all_team_members' | 'partial_members'
export type DocumentAccessMode = 'inherit' | PermissionEnum
export type LooseString<T extends string> = T | (string & {})
export type JsonObject = Record<string, unknown>
