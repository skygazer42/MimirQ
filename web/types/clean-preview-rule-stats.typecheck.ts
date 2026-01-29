import type { CleanPreviewResponse } from '@/types'

const _sample: CleanPreviewResponse = {
  markdown: '',
  applied_rules: 0,
  changed: false,
  // Typecheck: backend may include per-rule hit counts.
  rule_stats: [],
}

void _sample

