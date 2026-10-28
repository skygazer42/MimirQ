'use client'

import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowLeft, Loader2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { PageHeaderBar } from '@/components/ui/page-header-bar'
import { PageTitleIcon, type PageTitleIconName } from '@/components/ui/page-title-icon'
import { cn } from '@/lib/utils'
import { extractRequestIdFromError } from '@/lib/api-errors'
import styles from './operational-workspace.module.css'

export const workspaceStyles = styles

export function WorkspaceTableScroll({ children, label, stickyActions = false }: { children: ReactNode; label: string; stickyActions?: boolean }) {
  const container = useRef<HTMLDivElement>(null)
  const hintId = useId()
  const [overflow, setOverflow] = useState(false)
  useLayoutEffect(() => {
    const element = container.current!
    const update = () => setOverflow(element.scrollWidth > element.clientWidth + 1)
    const observer = new ResizeObserver(update)
    observer.observe(element)
    if (element.firstElementChild) observer.observe(element.firstElementChild)
    update()
    return () => observer.disconnect()
  }, [children])
  return <><p id={hintId} hidden={!overflow} className={styles.tableHint}>左右滑动查看完整字段</p><div ref={container} className={styles.tableScroll} data-sticky-actions={stickyActions} role={overflow ? 'region' : undefined} aria-label={overflow ? label : undefined} aria-describedby={overflow ? hintId : undefined} tabIndex={overflow ? 0 : undefined}>{children}</div></>
}

export function OperationalWorkspace({ title, icon, context, actions, toolbar, back, mode = 'scroll', children, className }: {
  title: string
  icon: PageTitleIconName
  context?: ReactNode
  actions?: ReactNode
  toolbar?: ReactNode
  back?: () => void
  mode?: 'scroll' | 'canvas'
  children: ReactNode
  className?: string
}) {
  return <section className={cn(styles.workspace, className)} data-operational-workspace={title}>
    <PageHeaderBar className={styles.header}><div className={styles.headerRow}>{back ? <Button variant="ghost" size="icon" className={styles.back} aria-label="返回上一级" onClick={back}><ArrowLeft /></Button> : null}<div className={styles.titleGroup}><div className={styles.heading}><PageTitleIcon name={icon} /><h1 title={title}>{title}</h1></div>{context ? <div className={styles.context}>{context}</div> : null}</div>{actions ? <div className={styles.actions}>{actions}</div> : null}</div></PageHeaderBar>
    {toolbar ? <div className={styles.toolbar}>{toolbar}</div> : null}
    <div className={cn(styles.body, mode === 'canvas' ? styles.canvasBody : styles.scrollBody)} data-workspace-content>{children}</div>
  </section>
}

export function WorkspaceMetrics({ items, className }: { items: Array<{ label: string; value: ReactNode; detail?: ReactNode; tone?: 'warning' | 'danger' }>; className?: string }) {
  return <dl className={cn(styles.metrics, className)}>{items.map(item => <div key={item.label}><dt>{item.label}</dt><dd data-tone={item.tone}>{item.value}</dd>{item.detail ? <small>{item.detail}</small> : null}</div>)}</dl>
}

export function WorkspaceNotice({ children, retry, retryLabel = '重新读取', pending = false }: { children: ReactNode; retry?: () => void; retryLabel?: string; pending?: boolean }) {
  const requestId = typeof children === 'string' ? extractRequestIdFromError(children) : undefined
  const message = requestId && typeof children === 'string' ? children.replace(/\s*\(request_id=[A-Za-z0-9._:-]+\)\s*$/, '') : children
  return <div role="alert" className={styles.notice}><div>{message}{requestId ? <details className="mt-1 text-xs text-muted-foreground"><summary className="cursor-pointer">错误详情</summary><p className="mt-1 break-all font-mono">request_id={requestId}</p></details> : null}</div>{retry ? <Button variant="ghost" disabled={pending} onClick={retry}>{pending ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : null}{retryLabel}</Button> : null}</div>
}

export function DirectoryWorkspace({ directory, children, pane, onPaneChange, directoryLabel = '目录', detailLabel = '详情' }: { directory: ReactNode; children: ReactNode; pane: 'directory' | 'detail'; onPaneChange: (pane: 'directory' | 'detail') => void; directoryLabel?: string; detailLabel?: string }) {
  return <><nav className={styles.mobileNavigation} aria-label="工作区视图"><Button variant="ghost" aria-pressed={pane === 'directory'} onClick={() => onPaneChange('directory')}>{directoryLabel}</Button><Button variant="ghost" aria-pressed={pane === 'detail'} onClick={() => onPaneChange('detail')}>{detailLabel}</Button></nav><div className={styles.split} data-pane={pane}><aside className={styles.directory}>{directory}</aside><div className={styles.reader}>{children}</div></div></>
}
