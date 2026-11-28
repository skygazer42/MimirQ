'use client'

import { Suspense, useEffect, useState } from 'react'
import dynamic from 'next/dynamic'
import { useSearchParams } from 'next/navigation'
import { AppFrame } from '@/components/app-frame'
import { NavigationVisibilityGate } from '@/components/auth/navigation-visibility-gate'
import { PageLoading } from '@/components/ui/page-loading'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Grid3X3, SlidersHorizontal } from '@/components/icons'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { canShowAdminControlledNavigationModule } from '@/lib/navigation-visibility'
import { Link } from '@/i18n/navigation'
import { ConversationEvaluation } from './_components/conversation-evaluation'
import styles from './evaluations.module.css'

const RegressionTestTab = dynamic(
  () => import('@/components/evaluation/regression-tab').then((mod) => mod.RegressionTestTab),
  { loading: () => <PageLoading message="正在加载评测集…" /> },
)
const QuerysetHealthTab = dynamic(
  () => import('@/components/evaluation/queryset-health-tab-client').then((mod) => mod.QuerysetHealthTab),
  { ssr: false, loading: () => <PageLoading message="正在加载健康度…" /> },
)
const TABS = [
  { id: 'conversation', label: '对话评测' },
  { id: 'regression', label: 'Golden 评测集' },
  { id: 'queryset_health', label: '检索集健康度' },
] as const
type EvaluationTab = (typeof TABS)[number]['id']
function parseTab(value: string | null): EvaluationTab {
  return TABS.find((tab) => tab.id === value)?.id ?? 'conversation'
}

export default function EvaluationsPage() {
  return (
    <NavigationVisibilityGate moduleKey="ragas" pageName="RAG 评测">
      <AppFrame>
        <Suspense fallback={<PageLoading message="正在加载评测…" />}>
          <EvaluationWorkspace />
        </Suspense>
      </AppFrame>
    </NavigationVisibilityGate>
  )
}

function EvaluationWorkspace() {
  const searchParams = useSearchParams()
  const tenantAccess = useTenantAccess()
  const activeTab = parseTab(searchParams.get('tab'))
  const [visited, setVisited] = useState<EvaluationTab[]>([activeTab])
  useEffect(() => {
    setVisited((previous) => (previous.includes(activeTab) ? previous : [...previous, activeTab]))
  }, [activeTab])

  function changeTab(value: string) {
    const url = new URL(window.location.href)
    url.searchParams.set('tab', parseTab(value))
    window.history.replaceState(null, '', url)
  }
  const showAblations =
    !tenantAccess.isLoading && canShowAdminControlledNavigationModule(tenantAccess.data, 'ablations')
  return (
    <div className={styles.workspace} data-evaluation-page>
      <Tabs value={activeTab} onValueChange={changeTab} className={styles.tabsRoot}>
        <header className={styles.header}>
          <div className={styles.heading}>
            <PageTitleIcon name="ragas-evaluation" />
            <h1>RAG 评测</h1>
          </div>
          <TabsList className={styles.tabs} aria-label="评测类型">
            {TABS.map((tab) => (
              <TabsTrigger key={tab.id} value={tab.id} className={styles.tab}>
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
          <div className={styles.headerActions}>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" aria-label="高级诊断">
                  <SlidersHorizontal aria-hidden="true" />
                  <span>高级诊断</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuItem asChild>
                  <Link href="/knowledge/similarity">
                    <Grid3X3 className="mr-2 size-4" />
                    向量相似度诊断
                  </Link>
                </DropdownMenuItem>
                {showAblations && (
                  <DropdownMenuItem asChild>
                    <Link href="/evaluations/ablations">
                      <SlidersHorizontal className="mr-2 size-4" />
                      检索调参对比
                    </Link>
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        {(activeTab === 'conversation' || visited.includes('conversation')) && (
          <TabsContent value="conversation" forceMount hidden={activeTab !== 'conversation'} className={styles.panel}>
            <ConversationEvaluation active={activeTab === 'conversation'} />
          </TabsContent>
        )}
        {(activeTab === 'regression' || visited.includes('regression')) && (
          <TabsContent value="regression" forceMount hidden={activeTab !== 'regression'} className={styles.panel}>
            <RegressionTestTab />
          </TabsContent>
        )}
        {(activeTab === 'queryset_health' || visited.includes('queryset_health')) && (
          <TabsContent
            value="queryset_health"
            forceMount
            hidden={activeTab !== 'queryset_health'}
            className={styles.scrollPanel}
          >
            <QuerysetHealthTab />
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
