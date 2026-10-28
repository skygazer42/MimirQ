'use client'

import { Suspense, useEffect, useState } from 'react'
import dynamic from 'next/dynamic'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
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

const RegressionTestTab = dynamic(() => import('@/components/evaluation/regression-tab').then(mod => mod.RegressionTestTab), { loading: () => <PageLoading message="正在加载评测集…" /> })
const QuerysetHealthTab = dynamic(() => import('@/components/evaluation/queryset-health-tab').then(mod => mod.QuerysetHealthTab), { loading: () => <PageLoading message="正在加载健康度…" /> })
const TABS = [{ id:'conversation', label:'对话评测' }, { id:'regression', label:'Golden 评测集' }, { id:'queryset_health', label:'检索集健康度' }] as const
type EvaluationTab = typeof TABS[number]['id']
function parseTab(value: string | null): EvaluationTab { return TABS.find(tab=>tab.id===value)?.id || 'conversation' }

export default function EvaluationsPage() {
  return <NavigationVisibilityGate moduleKey="ragas" pageName="RAG 评测"><AppFrame><Suspense fallback={<PageLoading message="正在加载评测…" />}><EvaluationWorkspace /></Suspense></AppFrame></NavigationVisibilityGate>
}

function EvaluationWorkspace() {
  const searchParams=useSearchParams()
  const pathname=usePathname()
  const router=useRouter()
  const tenantAccess=useTenantAccess()
  const [activeTab,setActiveTab]=useState<EvaluationTab>(()=>parseTab(searchParams.get('tab')))
  const [visited,setVisited]=useState<EvaluationTab[]>(()=>[parseTab(searchParams.get('tab'))])
  const urlTab=parseTab(searchParams.get('tab'))
  useEffect(()=>{setActiveTab(urlTab);setVisited(previous=>previous.includes(urlTab)?previous:[...previous,urlTab])},[urlTab])
  function changeTab(value: string) {
    const next=parseTab(value)
    setActiveTab(next);setVisited(previous=>previous.includes(next)?previous:[...previous,next])
    const query=new URLSearchParams(searchParams.toString());query.set('tab',next)
    router.replace(`${pathname}?${query.toString()}`,{scroll:false})
  }
  const showAblations=!tenantAccess.isLoading && canShowAdminControlledNavigationModule(tenantAccess.data,'ablations')
  return <div className={styles.workspace} data-evaluation-page>
    <header className={styles.header}>
      <div className={styles.heading}><PageTitleIcon name="ragas-evaluation" /><h1>RAG 评测</h1></div>
      <div className={styles.headerActions}><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost"><SlidersHorizontal aria-hidden="true" /><span>高级诊断</span></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="w-56">
        <DropdownMenuItem asChild><Link href="/knowledge/similarity"><Grid3X3 className="mr-2 size-4" />向量相似度诊断</Link></DropdownMenuItem>
        {showAblations && <DropdownMenuItem asChild><Link href="/evaluations/ablations"><SlidersHorizontal className="mr-2 size-4" />检索调参对比</Link></DropdownMenuItem>}
      </DropdownMenuContent></DropdownMenu></div>
    </header>
    <Tabs value={activeTab} onValueChange={changeTab} className={styles.tabsRoot}>
      <TabsList className={styles.tabs} aria-label="评测类型">{TABS.map(tab=><TabsTrigger key={tab.id} value={tab.id} className={styles.tab}>{tab.label}</TabsTrigger>)}</TabsList>
      {visited.includes('conversation') && <TabsContent value="conversation" forceMount hidden={activeTab!=='conversation'} className={styles.panel}><ConversationEvaluation active={activeTab==='conversation'} /></TabsContent>}
      {visited.includes('regression') && <TabsContent value="regression" forceMount hidden={activeTab!=='regression'} className={styles.panel}><RegressionTestTab embedded /></TabsContent>}
      {visited.includes('queryset_health') && <TabsContent value="queryset_health" forceMount hidden={activeTab!=='queryset_health'} className={styles.scrollPanel}><QuerysetHealthTab embedded /></TabsContent>}
    </Tabs>
  </div>
}
