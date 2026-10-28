'use client'

import dynamic from 'next/dynamic'
import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'
import styles from '@/components/chunk-preview/components/workbench/compare.module.css'
import '@/components/chunk-preview/components/workbench/config-dialog.module.css'
import '@/components/pipeline-options-panel.module.css'

const ChunkPreview = dynamic(
  () => import('@/components/chunk-preview').then((mod) => mod.ChunkPreview),
  {
    ssr: false,
    loading: () => <PageLoading message="正在加载切块预览…" srMessage="正在加载切块预览页面" />,
  }
)

export default function ChunkPreviewPage() {
  return (
    <AppFrame>
      <div className={styles.route}>
        <ChunkPreview />
      </div>
    </AppFrame>
  )
}
