type PreviewWarningLabels = {
  semanticNeedsReview: (count: number) => string
}

const SEMANTIC_NEEDS_REVIEW_RE = /^(\d+)\s+chunks?\s+flagged\s+needs_review\s+\(semantic heuristics\)$/i

export function formatPreviewWarningMessage(message: string, labels: PreviewWarningLabels): string {
  const normalized = String(message || '').trim()
  const semanticMatch = SEMANTIC_NEEDS_REVIEW_RE.exec(normalized)
  if (semanticMatch) {
    return labels.semanticNeedsReview(Number(semanticMatch[1]))
  }
  return normalized
}
