'use client'

import type { DragEventHandler, ReactNode } from 'react'
import { ChevronRight } from '@/components/icons'
import { Link } from '@/i18n/navigation'
import { cn } from '@/lib/utils'
import styles from './split-empty-studio.module.css'

export type SplitEmptyStep = {
  index: string
  title: string
  description: string
}

export type SplitEmptyShortcut =
  | {
      key: string
      icon: ReactNode
      title: string
      description: string
      href: string
      ariaLabel?: string
    }
  | {
      key: string
      icon: ReactNode
      title: string
      description: string
      onClick: () => void
      ariaLabel?: string
      ariaExpanded?: boolean
    }

export type SplitEmptyStudioProps = {
  illustration: ReactNode
  title: string
  titleId?: string
  description: string
  descriptionId?: string
  actions?: ReactNode
  status?: ReactNode
  stepsHeading?: string
  steps?: readonly SplitEmptyStep[]
  shortcutsHeading?: string
  shortcuts?: readonly SplitEmptyShortcut[]
  footerNote?: {
    label: string
    value: string
  }
  className?: string
  role?: 'region' | 'status'
  ariaLabel?: string
  ariaDescribedBy?: string
  dataAttributes?: Record<string, string | boolean | undefined>
  onDragEnter?: DragEventHandler<HTMLElement>
  onDragOver?: DragEventHandler<HTMLElement>
  onDragLeave?: DragEventHandler<HTMLElement>
  onDrop?: DragEventHandler<HTMLElement>
}

export function SplitEmptyStudio({
  illustration,
  title,
  titleId,
  description,
  descriptionId,
  actions,
  status,
  stepsHeading,
  steps,
  shortcutsHeading,
  shortcuts,
  footerNote,
  className,
  role,
  ariaLabel,
  ariaDescribedBy,
  dataAttributes,
  onDragEnter,
  onDragOver,
  onDragLeave,
  onDrop,
}: Readonly<SplitEmptyStudioProps>) {
  return (
    <section
      className={cn(styles.studio, className)}
      role={role}
      aria-label={ariaLabel}
      aria-describedby={ariaDescribedBy}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      {...dataAttributes}
    >
      <div className={styles.primaryPane}>
        <div className={styles.primaryInner}>
          <div className={styles.illustration} aria-hidden="true">
            {illustration}
          </div>
          <h2 id={titleId} className={styles.title}>
            {title}
          </h2>
          <p id={descriptionId} className={styles.description}>
            {description}
          </p>
          {actions ? <div className={styles.actions}>{actions}</div> : null}
          {status ? <div className={styles.statusSlot}>{status}</div> : null}
        </div>
      </div>

      <aside className={styles.guidePane} aria-label={stepsHeading ?? shortcutsHeading ?? '操作指引'}>
        <div className={styles.guideInner}>
          {steps && steps.length > 0 ? (
            <div className={styles.group}>
              {stepsHeading ? <h3 className={styles.groupHeading}>{stepsHeading}</h3> : null}
              <ol className={styles.stepList}>
                {steps.map((step) => (
                  <li key={step.index} className={styles.stepRow}>
                    <span className={styles.stepIndex} aria-hidden="true">
                      {step.index}
                    </span>
                    <div className={styles.stepCopy}>
                      <span className={styles.stepTitle}>{step.title}</span>
                      <span className={styles.stepDescription}>{step.description}</span>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}

          {shortcuts && shortcuts.length > 0 ? (
            <div className={styles.group}>
              {shortcutsHeading ? <h3 className={styles.groupHeading}>{shortcutsHeading}</h3> : null}
              <div className={styles.shortcutList}>
                {shortcuts.map((item) => {
                  const content = (
                    <>
                      <span className={styles.shortcutIcon} aria-hidden="true">
                        {item.icon}
                      </span>
                      <span className={styles.shortcutCopy}>
                        <span className={styles.shortcutTitle}>{item.title}</span>
                        <span className={styles.shortcutDescription}>{item.description}</span>
                      </span>
                      <ChevronRight className={styles.shortcutChevron} aria-hidden="true" />
                    </>
                  )

                  if ('href' in item) {
                    return (
                      <Link
                        key={item.key}
                        href={item.href}
                        className={cn('focus-ring', styles.shortcutRow)}
                        aria-label={item.ariaLabel}
                      >
                        {content}
                      </Link>
                    )
                  }

                  return (
                    <button
                      key={item.key}
                      type="button"
                      className={cn('focus-ring', styles.shortcutRow)}
                      aria-label={item.ariaLabel}
                      aria-expanded={item.ariaExpanded}
                      onClick={item.onClick}
                    >
                      {content}
                    </button>
                  )
                })}
              </div>
            </div>
          ) : null}

          {footerNote ? (
            <div className={styles.footerNote}>
              <span className={styles.footerNoteLabel}>{footerNote.label}</span>
              <span className={styles.footerNoteValue}>{footerNote.value}</span>
            </div>
          ) : null}
        </div>
      </aside>
    </section>
  )
}
