'use client'

import { AlertCircle, ChevronDown } from '@/components/icons'
import { cn } from '@/lib/utils'
import styles from './parsing-compare.module.css'

const FLAG_LABELS = new Map([
  ['parse_score_low', '解析分低'],
  ['ocr_low_confidence', 'OCR低置信'],
  ['table_structure_low_confidence', '表格结构低置信'],
  ['reading_order_unstable', '版面顺序不稳'],
  ['noise_removal_risky', '噪声清理风险'],
  ['tag_sidecar_recommended', '建议TAG'],
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function getQualityGateGrade(value: unknown): 'pass' | 'warn' | 'fail' | null {
  if (!isRecord(value)) return null
  const grade = value.grade
  return grade === 'pass' || grade === 'warn' || grade === 'fail' ? grade : null
}

function getQualityGateReasons(value: unknown): string[] {
  if (!isRecord(value) || !Array.isArray(value.reasons)) return []
  return value.reasons.filter((item): item is string => typeof item === 'string')
}

function getQualityEnhancementErrors(value: unknown): string[] {
  if (!isRecord(value) || !isRecord(value.evidence)) return []
  const evidence = value.evidence
  return (
    [
      ['vlm_correction', '视觉校正'],
      ['image_ocr', '图片文字识别'],
    ] as const
  ).flatMap(([key, label]) => {
    const audit = evidence[key]
    if (!isRecord(audit) || typeof audit.error !== 'string' || audit.error.length === 0) return []
    return [`${label}未完成：${audit.error}`]
  })
}

function readBackendName(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const name = value.trim()
  return name.length === 0 ? null : name
}

function getQualityEvidenceItems(qualityGate: unknown, pdfQuality: unknown): string[] {
  const pieces: string[] = []
  const gateEvidence = isRecord(qualityGate) && isRecord(qualityGate.evidence) ? qualityGate.evidence : undefined
  const textQuality = isRecord(gateEvidence?.text_quality) ? gateEvidence.text_quality : undefined
  const parseQuality = isRecord(gateEvidence?.parse_quality) ? gateEvidence.parse_quality : undefined
  const parseQualityGate = isRecord(gateEvidence?.parse_quality_gate) ? gateEvidence.parse_quality_gate : undefined
  const parseQualityFlags = isRecord(parseQualityGate?.flags) ? parseQualityGate.flags : undefined
  if (isRecord(pdfQuality)) {
    if (typeof pdfQuality.score === 'number') pieces.push(`pdf_score=${pdfQuality.score.toFixed(3)}`)
    if (typeof pdfQuality.reading_order_score === 'number') {
      pieces.push(`阅读顺序评分=${pdfQuality.reading_order_score.toFixed(3)}`)
    } else if (pdfQuality.reading_order_score === null) {
      pieces.push('阅读顺序未评估')
    }
  }
  if (typeof parseQuality?.score === 'number') pieces.push(`parse_score=${parseQuality.score.toFixed(3)}`)
  if (typeof textQuality?.content_chars === 'number') pieces.push(`content_chars=${textQuality.content_chars}`)
  if (typeof textQuality?.density === 'number') pieces.push(`density=${textQuality.density.toFixed(3)}`)
  if (typeof textQuality?.replacement_ratio === 'number') {
    pieces.push(`replacement_ratio=${textQuality.replacement_ratio.toFixed(3)}`)
  }
  if (Array.isArray(gateEvidence?.fallback_attempts) && gateEvidence.fallback_attempts.length > 0) {
    const fallbackBackends = [
      readBackendName(gateEvidence.fallback_initial_backend),
      readBackendName(gateEvidence.fallback_final_backend),
    ].filter((value): value is string => value !== null)
    if (fallbackBackends.length > 0) {
      pieces.push(`fallback=${fallbackBackends.join('→')}`)
    }
  }
  if (parseQualityFlags !== undefined) {
    const activeFlags = Object.entries(parseQualityFlags)
      .filter(([, value]) => value === true)
      .map(([key]) => FLAG_LABELS.get(key) ?? key)
    if (activeFlags.length > 0) pieces.push(`质量标记=${activeFlags.join('、')}`)
  }

  return pieces
}

export function ParsingQualityNotice({
  qualityGate,
  pdfQuality,
}: Readonly<{ qualityGate: unknown; pdfQuality: unknown }>) {
  const qualityGrade = getQualityGateGrade(qualityGate)
  const qualityReasons = getQualityGateReasons(qualityGate)
  const qualityEvidenceItems = getQualityEvidenceItems(qualityGate, pdfQuality)
  const enhancementErrors = getQualityEnhancementErrors(qualityGate)
  const readingOrderUnavailable = isRecord(pdfQuality) && pdfQuality.reading_order_score === null
  if (
    (qualityGate === null || qualityGate === undefined || qualityGrade === 'pass') &&
    enhancementErrors.length === 0 &&
    !readingOrderUnavailable
  )
    return null

  return (
    <details className={cn(styles.quality, qualityGrade === 'fail' && styles.qualityFail)}>
      <summary>
        <AlertCircle className="size-3.5 shrink-0" />
        <span>
          {qualityGrade === 'fail'
            ? '解析质量未通过检查'
            : enhancementErrors.length > 0
              ? '部分解析增强未完成'
              : readingOrderUnavailable
                ? '阅读顺序未评估'
                : qualityGrade === null
                  ? '质量评估状态未知'
                  : '解析内容需要核对'}
        </span>
        <ChevronDown className="ml-auto size-3.5" />
      </summary>
      <div>
        <p>{qualityReasons.length > 0 ? qualityReasons.join(' · ') : '请对照原文检查解析结果。'}</p>
        {enhancementErrors.map((message) => (
          <p key={message}>{message}</p>
        ))}
        {qualityEvidenceItems.length ? <p>{qualityEvidenceItems.join(' · ')}</p> : null}
      </div>
    </details>
  )
}
