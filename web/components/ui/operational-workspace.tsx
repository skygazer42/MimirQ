'use client'

import {
  Children,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Loader2,
  RefreshCw,
  X,
} from '@/components/icons'
import { Button } from '@/components/ui/button'
import { PageHeaderBar } from '@/components/ui/page-header-bar'
import { PageTitleIcon, type PageTitleIconName } from '@/components/ui/page-title-icon'
import { cn } from '@/lib/utils'
import { extractRequestIdFromError, splitApiErrorDisplay } from '@/lib/api-errors'
import styles from './operational-workspace.module.css'

const AUTO_MINIMIZE_MS = 6000

type NoticeStackContextValue = {
  inStack: boolean
  minimize: () => void
  reportDetailsOpen: (open: boolean) => void
}

const NoticeStackContext = createContext<NoticeStackContextValue | null>(null)

export const workspaceStyles = styles

export function WorkspaceStarter({
  labelledBy,
  dropzone,
  entries,
  steps,
  className,
}: {
  labelledBy?: string
  dropzone?: ReactNode
  entries?: ReadonlyArray<{ title: string; description: string; icon: ReactNode; onClick: () => void }>
  steps?: readonly string[]
  className?: string
}) {
  return (
    <section className={cn(styles.starter, className)} aria-labelledby={labelledBy} data-page-scroll-container="true">
      <div className={styles.starterStack}>
        {dropzone}
        {entries ? (
          <div className={styles.starterEntries}>
            {entries.map((entry) => (
              <button key={entry.title} type="button" className={styles.starterEntry} onClick={entry.onClick}>
                <span className={styles.starterEntryIcon} aria-hidden="true">
                  {entry.icon}
                </span>
                <span className={styles.starterEntryCopy}>
                  <strong>{entry.title}</strong>
                  <span>{entry.description}</span>
                </span>
                <ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              </button>
            ))}
          </div>
        ) : null}
        {steps ? (
          <ol className={styles.starterPipeline}>
            {steps.map((step, index) => (
              <li key={step}>
                {index > 0 ? <ChevronRight className={styles.pipelineSeparator} aria-hidden="true" /> : null}
                <span className={styles.pipelineNumber} aria-hidden="true">
                  {index + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </section>
  )
}

export function WorkspaceEmptyCard({
  icon,
  title,
  description,
  primaryAction,
  secondaryAction,
  className,
}: {
  icon: ReactNode
  title: string
  description: string
  primaryAction?: ReactNode
  secondaryAction?: ReactNode
  className?: string
}) {
  return (
    <div className={cn(styles.emptyCard, className)}>
      <span className={styles.emptyCardIcon} aria-hidden="true">
        {icon}
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
      {primaryAction || secondaryAction ? (
        <div className={styles.emptyCardActions}>
          {primaryAction}
          {secondaryAction}
        </div>
      ) : null}
    </div>
  )
}

export function WorkspaceStatPill({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn(styles.statPill, className)}>{children}</span>
}

export function WorkspaceTableScroll({
  children,
  label,
  stickyActions = false,
}: {
  children: ReactNode
  label: string
  stickyActions?: boolean
}) {
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
  return (
    <>
      <p id={hintId} hidden={!overflow} className={styles.tableHint}>
        左右滑动查看完整字段
      </p>
      <div
        ref={container}
        className={styles.tableScroll}
        data-sticky-actions={stickyActions}
        role={overflow ? 'region' : undefined}
        aria-label={overflow ? label : undefined}
        aria-describedby={overflow ? hintId : undefined}
        tabIndex={overflow ? 0 : undefined}
      >
        {children}
      </div>
    </>
  )
}

export function OperationalWorkspace({
  title,
  icon,
  context,
  actions,
  toolbar,
  back,
  mode = 'scroll',
  children,
  className,
}: {
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
  return (
    <section className={cn(styles.workspace, className)} data-operational-workspace={title}>
      <PageHeaderBar className={styles.header}>
        <div className={styles.headerRow}>
          {back ? (
            <Button variant="ghost" size="icon" className={styles.back} aria-label="返回上一级" onClick={back}>
              <ArrowLeft />
            </Button>
          ) : null}
          <div className={styles.titleGroup}>
            <div className={styles.heading}>
              <PageTitleIcon name={icon} />
              <h1 title={title}>{title}</h1>
            </div>
            {context ? <div className={styles.context}>{context}</div> : null}
          </div>
          {actions ? <div className={styles.actions}>{actions}</div> : null}
        </div>
      </PageHeaderBar>
      {toolbar ? <div className={styles.toolbar}>{toolbar}</div> : null}
      <div
        className={cn(styles.body, mode === 'canvas' ? styles.canvasBody : styles.scrollBody)}
        data-workspace-content
      >
        {children}
      </div>
    </section>
  )
}

export function WorkspaceMetrics({
  items,
  className,
}: {
  items: Array<{ label: string; value: ReactNode; detail?: ReactNode; tone?: 'warning' | 'danger' }>
  className?: string
}) {
  return (
    <dl className={cn(styles.metrics, className)}>
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd data-tone={item.tone}>
            {item.value}
            {item.detail == null ? null : <small className="font-normal">{item.detail}</small>}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export function WorkspaceNoticeStack({
  children,
  className,
  ariaLabel,
  autoMinimizeMs = AUTO_MINIMIZE_MS,
}: {
  children: ReactNode
  className?: string
  ariaLabel?: string
  autoMinimizeMs?: number
}) {
  const items = Children.toArray(children).filter(Boolean)
  const count = items.length
  const [minimized, setMinimized] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  const [detailsOpenCount, setDetailsOpenCount] = useState(0)
  const prevCountRef = useRef(count)
  const reportDetailsOpen = useCallback((open: boolean) => {
    setDetailsOpenCount((prev) => Math.max(0, prev + (open ? 1 : -1)))
  }, [])

  // Re-open briefly when a new notice joins the stack so fresh failures aren't silently missed.
  useEffect(() => {
    if (count > prevCountRef.current) {
      setMinimized(false)
    }
    prevCountRef.current = count
  }, [count])

  useEffect(() => {
    if (count === 0 || minimized || hovered || focused || detailsOpenCount > 0 || autoMinimizeMs <= 0) return
    const timer = window.setTimeout(() => {
      setMinimized(true)
    }, autoMinimizeMs)
    return () => window.clearTimeout(timer)
  }, [autoMinimizeMs, count, detailsOpenCount, focused, hovered, minimized])

  if (count === 0) return null

  const stackContext: NoticeStackContextValue = {
    inStack: true,
    minimize: () => setMinimized(true),
    reportDetailsOpen,
  }

  return (
    <div
      className={cn(styles.noticeStack, minimized && styles.noticeStackMinimized, className)}
      aria-label={ariaLabel}
      data-workspace-notice-stack
      data-minimized={minimized ? 'true' : 'false'}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => setFocused(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setFocused(false)
        }
      }}
    >
      {minimized ? (
        <button
          type="button"
          className={cn('focus-ring', styles.noticeOrb)}
          aria-label={`展开 ${count} 条异常提示`}
          aria-expanded={false}
          title={count > 1 ? `有 ${count} 条异常提示，点击展开查看` : '有异常提示，点击展开查看'}
          data-workspace-notice-orb
          onClick={() => {
            setMinimized(false)
            setHovered(false)
            setFocused(false)
          }}
        >
          <AlertCircle aria-hidden="true" />
          <span className={cn(styles.noticeOrbDot, count > 1 && styles.noticeOrbBadge)} aria-hidden="true">
            {count > 1 ? count : null}
          </span>
        </button>
      ) : (
        <NoticeStackContext.Provider value={stackContext}>{items}</NoticeStackContext.Provider>
      )}
    </div>
  )
}

export function WorkspaceNotice({
  title,
  titleAs = 'div',
  children,
  error,
  fallbackMessage,
  requestId: explicitRequestId,
  tone = 'error',
  placement = 'inline',
  retry,
  retryLabel = '重新读取',
  retryAriaLabel,
  retryDisabled = false,
  pending = false,
  onDismiss,
  dismissLabel = '关闭提示',
  className,
}: {
  title?: string
  titleAs?: 'div' | 'h5'
  children?: ReactNode
  error?: unknown
  fallbackMessage?: string
  requestId?: string
  tone?: 'error' | 'warning' | 'info'
  placement?: 'inline' | 'floating'
  retry?: () => void
  retryLabel?: string
  retryAriaLabel?: string
  retryDisabled?: boolean
  pending?: boolean
  onDismiss?: () => void
  dismissLabel?: string
  className?: string
}) {
  const stack = useContext(NoticeStackContext)
  if (placement === 'floating' && !stack?.inStack) {
    return (
      <WorkspaceNoticeStack>
        <WorkspaceNotice
          title={title}
          titleAs={titleAs}
          error={error}
          fallbackMessage={fallbackMessage}
          requestId={explicitRequestId}
          tone={tone}
          placement="inline"
          retry={retry}
          retryLabel={retryLabel}
          retryAriaLabel={retryAriaLabel}
          retryDisabled={retryDisabled}
          pending={pending}
          onDismiss={onDismiss}
          dismissLabel={dismissLabel}
          className={className}
        >
          {children}
        </WorkspaceNotice>
      </WorkspaceNoticeStack>
    )
  }

  return (
    <WorkspaceNoticeCard
      title={title}
      titleAs={titleAs}
      error={error}
      fallbackMessage={fallbackMessage}
      requestId={explicitRequestId}
      tone={tone}
      inFloatingStack={Boolean(stack?.inStack)}
      onMinimize={stack?.minimize}
      onDetailsToggle={stack?.reportDetailsOpen}
      retry={retry}
      retryLabel={retryLabel}
      retryAriaLabel={retryAriaLabel}
      retryDisabled={retryDisabled}
      pending={pending}
      onDismiss={onDismiss}
      dismissLabel={dismissLabel}
      className={className}
    >
      {children}
    </WorkspaceNoticeCard>
  )
}

function WorkspaceNoticeCard({
  title,
  titleAs = 'div',
  children,
  error,
  fallbackMessage,
  requestId: explicitRequestId,
  tone = 'error',
  inFloatingStack = false,
  onMinimize,
  onDetailsToggle,
  retry,
  retryLabel = '重新读取',
  retryAriaLabel,
  retryDisabled = false,
  pending = false,
  onDismiss,
  dismissLabel = '关闭提示',
  className,
}: {
  title?: string
  titleAs?: 'div' | 'h5'
  children?: ReactNode
  error?: unknown
  fallbackMessage?: string
  requestId?: string
  tone?: 'error' | 'warning' | 'info'
  inFloatingStack?: boolean
  onMinimize?: () => void
  onDetailsToggle?: (open: boolean) => void
  retry?: () => void
  retryLabel?: string
  retryAriaLabel?: string
  retryDisabled?: boolean
  pending?: boolean
  onDismiss?: () => void
  dismissLabel?: string
  className?: string
}) {
  const [copiedId, setCopiedId] = useState(false)
  const detailsOpenRef = useRef(false)
  const parsedError = error !== undefined ? splitApiErrorDisplay(error, fallbackMessage) : undefined
  const parsedString = typeof children === 'string' ? splitApiErrorDisplay(children, fallbackMessage) : undefined
  const requestId =
    explicitRequestId ??
    parsedError?.requestId ??
    parsedString?.requestId ??
    (typeof children === 'string' ? extractRequestIdFromError(children) : undefined)
  const body = parsedString ? parsedString.message : (children ?? parsedError?.message)

  useEffect(() => {
    return () => {
      if (detailsOpenRef.current) {
        detailsOpenRef.current = false
        onDetailsToggle?.(false)
      }
    }
  }, [onDetailsToggle])

  async function copyRequestId() {
    if (!requestId) return
    try {
      await navigator.clipboard.writeText(requestId)
      setCopiedId(true)
      window.setTimeout(() => setCopiedId(false), 1800)
    } catch {
      // Clipboard may be unavailable in non-secure contexts; keep raw selectable text visible.
    }
  }

  return (
    <div
      role="alert"
      data-tone={tone}
      data-placement={inFloatingStack ? 'floating' : 'inline'}
      className={cn(styles.notice, className)}
    >
      <span className={styles.noticeIcon} aria-hidden="true">
        <AlertCircle />
      </span>
      <div className={styles.noticeBody}>
        {title ? (
          titleAs === 'h5' ? (
            <h5 className={styles.noticeTitle}>{title}</h5>
          ) : (
            <div className={styles.noticeTitle}>{title}</div>
          )
        ) : null}
        {body ? <div className={title ? styles.noticeDescription : styles.noticeTitle}>{body}</div> : null}
        {requestId ? (
          <details
            className={styles.noticeDetails}
            onToggle={(event) => {
              const isOpen = event.currentTarget.open
              if (detailsOpenRef.current !== isOpen) {
                detailsOpenRef.current = isOpen
                onDetailsToggle?.(isOpen)
              }
            }}
          >
            <summary>错误详情</summary>
            <div className={styles.noticeDetailRow}>
              <p className="break-all font-mono">request_id={requestId}</p>
              <button
                type="button"
                className={styles.noticeCopy}
                aria-label="复制诊断编号"
                onClick={() => void copyRequestId()}
              >
                {copiedId ? <Check /> : <Copy />}
                <span>{copiedId ? '已复制' : '复制'}</span>
              </button>
            </div>
          </details>
        ) : null}
      </div>
      {retry || onDismiss || (inFloatingStack && onMinimize) ? (
        <div className={styles.noticeActions}>
          {retry ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className={styles.noticeRetry}
              aria-label={retryAriaLabel}
              disabled={pending || retryDisabled}
              onClick={retry}
            >
              {pending ? (
                <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <RefreshCw aria-hidden="true" />
              )}
              <span>{retryLabel}</span>
            </Button>
          ) : null}
          {inFloatingStack && onMinimize ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className={styles.noticeDismiss}
              aria-label="收起提示"
              title="最小化到右下角"
              onClick={onMinimize}
            >
              <ChevronDown aria-hidden="true" />
            </Button>
          ) : null}
          {onDismiss ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className={styles.noticeDismiss}
              aria-label={dismissLabel}
              onClick={onDismiss}
            >
              <X aria-hidden="true" />
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export function DirectoryWorkspace({
  directory,
  children,
  pane,
  onPaneChange,
  directoryLabel = '目录',
  detailLabel = '详情',
}: {
  directory: ReactNode
  children: ReactNode
  pane: 'directory' | 'detail'
  onPaneChange: (pane: 'directory' | 'detail') => void
  directoryLabel?: string
  detailLabel?: string
}) {
  return (
    <>
      <nav className={styles.mobileNavigation} aria-label="工作区视图">
        <Button variant="ghost" aria-pressed={pane === 'directory'} onClick={() => onPaneChange('directory')}>
          {directoryLabel}
        </Button>
        <Button variant="ghost" aria-pressed={pane === 'detail'} onClick={() => onPaneChange('detail')}>
          {detailLabel}
        </Button>
      </nav>
      <div className={styles.split} data-pane={pane}>
        <aside className={styles.directory}>{directory}</aside>
        <div className={styles.reader}>{children}</div>
      </div>
    </>
  )
}
