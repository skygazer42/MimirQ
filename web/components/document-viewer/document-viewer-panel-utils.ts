"use client"

import type { Citation } from "@/types"

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function toFiniteNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

export function toCitation(value: unknown): Citation | null {
  if (!isRecord(value)) return null
  const document_id = typeof value.document_id === "string" ? value.document_id : ""
  const document_name = typeof value.document_name === "string" ? value.document_name : ""
  const chunk_content = typeof value.chunk_content === "string" ? value.chunk_content : ""
  const relevance_score = toFiniteNumber(value.relevance_score) ?? 0
  if (!document_id || !document_name) return null
  const matched_terms = Array.isArray(value.matched_terms)
    ? value.matched_terms.filter((item): item is string => typeof item === "string")
    : undefined
  const chunk_id = typeof value.chunk_id === "string" ? value.chunk_id : undefined
  const page_number = toFiniteNumber(value.page_number)
  const chunk_index = toFiniteNumber(value.chunk_index)
  const start_char = toFiniteNumber(value.start_char)
  const end_char = toFiniteNumber(value.end_char)

  return {
    document_id,
    document_name,
    chunk_content,
    relevance_score,
    ...(chunk_id ? { chunk_id } : {}),
    ...(matched_terms?.length ? { matched_terms } : {}),
    ...(page_number !== undefined ? { page_number } : {}),
    ...(chunk_index !== undefined ? { chunk_index } : {}),
    ...(start_char !== undefined ? { start_char } : {}),
    ...(end_char !== undefined ? { end_char } : {}),
  }
}
