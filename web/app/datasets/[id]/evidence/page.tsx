'use client'

import { useParams, useSearchParams } from 'next/navigation'

import { AppFrame } from '@/components/app-frame'
import { EvidenceSuiteWorkbench } from '@/components/evidence/evidence-suite-workbench'

export default function DatasetEvidencePage() {
  const { id: datasetId } = useParams<{ id: string }>()
  const searchParams = useSearchParams()
  const initialFeedbackId = searchParams.get('feedback_id')?.trim()

  return (
    <AppFrame>
      {datasetId ? (
        <EvidenceSuiteWorkbench
          datasetId={datasetId}
          initialFeedbackId={initialFeedbackId === '' ? undefined : initialFeedbackId}
        />
      ) : (
        <p className="p-6 text-sm">未取得数据集。</p>
      )}
    </AppFrame>
  )
}
