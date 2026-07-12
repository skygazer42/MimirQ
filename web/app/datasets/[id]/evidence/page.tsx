'use client'

import { useMemo } from 'react'
import { useParams, useSearchParams } from 'next/navigation'
import { Activity, ArrowLeft, BarChart3, FileSearch, ShieldCheck, Settings2, Table2 } from 'lucide-react'

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

  return (
    <AppFrame>
      <PageScaffold
        title="证据库（Evidence Workbench）"
        badge="Ground Truth"
        icon={ShieldCheck}
        iconColor="text-success"
        description={<span className="text-sm text-muted-foreground text-pretty">持久化证据资产（Suites/Items）+ 审核流 + 一键同步到回归用例库。</span>}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" className="gap-2" onClick={() => router.push('/datasets')}>
              <ArrowLeft className="w-4 h-4" aria-hidden="true" />
              返回
            </Button>
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/health`)}>
                <Activity className="w-4 h-4" aria-hidden="true" />
                健康
              </Button>
            ) : null}
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/profile`)}>
                <BarChart3 className="w-4 h-4" aria-hidden="true" />
                数据画像
              </Button>
            ) : null}
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/precheck`)}>
                <FileSearch className="w-4 h-4" aria-hidden="true" />
                预检扫描
              </Button>
            ) : null}
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                <Settings2 className="w-4 h-4" aria-hidden="true" />
                入库策略
              </Button>
            ) : null}
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/tables`)}>
                <Table2 className="w-4 h-4" aria-hidden="true" />
                表格 / TAG
              </Button>
            ) : null}
          </div>
        }
      >
        {datasetId ? <EvidenceSuiteWorkbench datasetId={datasetId} initialFeedbackId={initialFeedbackId} /> : null}
      </PageScaffold>
    </AppFrame>
  )
}
