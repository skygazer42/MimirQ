'use client'

import { useSyncExternalStore } from 'react'
import { AppFrame } from '@/components/app-frame'
import { NavigationVisibilityGate } from '@/components/auth/navigation-visibility-gate'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Link2, Loader2, MoreHorizontal, Plus, RefreshCw } from '@/components/icons'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { PromptDialogs } from './prompt-dialogs'
import { PromptTable } from './prompt-table'
import { usePromptTemplates } from './use-prompt-templates'
import styles from './prompts.module.css'

export default function PromptsPage() {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return (
    <NavigationVisibilityGate moduleKey="prompts" pageName="提示词">
      <PromptsPageContent key={sessionKey} sessionKey={sessionKey} />
    </NavigationVisibilityGate>
  )
}
function PromptsPageContent({ sessionKey }: Readonly<{ sessionKey: string }>) {
  const controller = usePromptTemplates(sessionKey)
  return (
    <AppFrame>
      <section className={styles.workspace} data-prompts-workbench>
        <header className={styles.header}>
          <div className={styles.heading}>
            <PageTitleIcon name="prompts" />
            <h1>提示词</h1>
          </div>
          {controller.canManage ? (
            <div className={styles.headerActions}>
              <div className={styles.secondaryActions}>
                <Button variant="ghost" data-prompt-bindings onClick={controller.openBindings}>
                  <Link2 />
                  场景绑定
                </Button>
                <Button
                  variant="ghost"
                  disabled={Boolean(controller.busy) || controller.query.isLoading}
                  onClick={() => {
                    void controller.syncBuiltins()
                  }}
                >
                  {controller.busy === 'sync' ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                  {controller.busy === 'sync' ? '同步中' : '同步内置模板'}
                </Button>
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className={styles.mobileActions}
                    data-prompt-mobile-actions
                    aria-label="模板管理操作"
                  >
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className={styles.menu}>
                  <DropdownMenuItem onSelect={controller.openBindings}>场景绑定</DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={Boolean(controller.busy) || controller.query.isLoading}
                    onSelect={() => {
                      void controller.syncBuiltins()
                    }}
                  >
                    同步内置模板
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button
                className={styles.primary}
                data-prompt-create
                disabled={Boolean(controller.busy)}
                onClick={() => controller.openEditor()}
              >
                <Plus />
                创建模板
              </Button>
            </div>
          ) : null}
        </header>
        <PromptTable controller={controller} />
        <PromptDialogs controller={controller} />
      </section>
    </AppFrame>
  )
}
