import type { CleanPreviewResponse } from '@/types'
import { detachPromise } from '@/lib/utils'


const _sample: CleanPreviewResponse = {
  markdown: '',
  applied_rules: 0,
  changed: false,
  // Typecheck: backend may include per-rule hit counts.
  rule_stats: [],
}

detachPromise(_sample)

