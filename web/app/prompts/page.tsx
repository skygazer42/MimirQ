'use client'

import { AppFrame } from '@/components/app-frame'
import { NavigationVisibilityGate } from '@/components/auth/navigation-visibility-gate'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Link2, Loader2, MoreHorizontal, Plus, RefreshCw } from '@/components/icons'
import { PromptDialogs } from './prompt-dialogs'
import { PromptTable } from './prompt-table'
import { usePromptTemplates } from './use-prompt-templates'
import styles from './prompts.module.css'

export default function PromptsPage() {
  return <NavigationVisibilityGate moduleKey="prompts" pageName="提示词"><PromptsPageContent/></NavigationVisibilityGate>
}
function PromptsPageContent() {
  const c=usePromptTemplates()
  return <AppFrame><section className={styles.workspace} data-prompts-workbench>
    <header className={styles.header}><div className={styles.heading}><PageTitleIcon name="prompts"/><h1>提示词</h1></div>
      {c.canManage?<div className={styles.headerActions}>
        <div className={styles.secondaryActions}><Button variant="ghost" data-prompt-bindings onClick={c.openBindings}><Link2/>场景绑定</Button><Button variant="ghost" disabled={Boolean(c.busy)||c.query.isLoading} onClick={()=>{void c.syncBuiltins()}}>{c.busy==='sync'?<Loader2 className="animate-spin"/>:<RefreshCw/>}{c.busy==='sync'?'同步中':'同步内置模板'}</Button></div>
        <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className={styles.mobileActions} data-prompt-mobile-actions aria-label="模板管理操作"><MoreHorizontal/></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className={styles.menu}><DropdownMenuItem onSelect={c.openBindings}>场景绑定</DropdownMenuItem><DropdownMenuItem disabled={Boolean(c.busy)||c.query.isLoading} onSelect={()=>{void c.syncBuiltins()}}>同步内置模板</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
        <Button className={styles.primary} data-prompt-create disabled={Boolean(c.busy)} onClick={()=>c.openEditor()}><Plus/>创建模板</Button>
      </div>:null}
    </header>
    <PromptTable controller={c}/><PromptDialogs controller={c}/>
  </section></AppFrame>
}
