'use client'

import { useMemo } from 'react'
import { useParams, useSearchParams } from 'next/navigation'
import { Activity, ArrowLeft, BarChart3, FileSearch, ShieldCheck, Settings2, Table2 } from '@/components/icons'

import { AppFrame } from '@/components/app-frame'
import { EvidenceSuiteWorkbench } from '@/components/evidence/evidence-suite-workbench'
import { Button } from '@/components/ui/button'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { useRouter } from '@/i18n/navigation'

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return null
}

export default function DatasetEvidencePage() {
  const router = useRouter()
  const params = useParams()
  const searchParams = useSearchParams()
  const datasetId = useMemo(() => asDatasetId((params as Record<string, unknown>).id), [params])
  const initialFeedbackId = useMemo(() => {
    const raw = searchParams.get('feedback_id')
    return raw?.trim() ? raw.trim() : undefined
  }, [searchParams])

  return <AppFrame>{datasetId ? <EvidenceSuiteWorkbench datasetId={datasetId} initialFeedbackId={initialFeedbackId} /> : <p className="p-6 text-sm">未取得数据集。</p>}</AppFrame>
}
