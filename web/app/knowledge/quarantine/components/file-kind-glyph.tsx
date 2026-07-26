'use client'

import { getDocumentKind } from '@/components/ingestion/monitor-utils'
import { cn } from '@/lib/utils'

export function FileKindGlyph({
  kind,
  className,
}: Readonly<{ kind: ReturnType<typeof getDocumentKind>; className?: string }>) {
  if (kind === 'pdf') {
    return (
      <svg
        viewBox="0 0 24 24"
        className={cn('h-4 w-4', className)}
        aria-hidden="true"
      >
        <path d="M7 3.5h7l4 4V20.5H7z" fill="currentColor" opacity="0.18" />
        <path
          d="M14 3.5v4h4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        <path
          d="M8.5 15.5h7"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <path
          d="M8.5 18h5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    )
  }

  if (kind === 'markdown') {
    return (
      <svg
        viewBox="0 0 24 24"
        className={cn('h-4 w-4', className)}
        aria-hidden="true"
      >
        <rect
          x="5"
          y="5"
          width="14"
          height="14"
          rx="3"
          fill="currentColor"
          opacity="0.12"
        />
        <path
          d="M8 16V9l2.5 3 2.5-3v7"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M15.5 10.5v4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <path
          d="m14 13 1.5 1.5L17 13"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    )
  }

  if (kind === 'spreadsheet') {
    return (
      <svg
        viewBox="0 0 24 24"
        className={cn('h-4 w-4', className)}
        aria-hidden="true"
      >
        <rect
          x="5"
          y="4.5"
          width="14"
          height="15"
          rx="2.5"
          fill="currentColor"
          opacity="0.12"
        />
        <path
          d="M5 9.5h14M10 4.5v15M14.5 9.5v10"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    )
  }

  if (kind === 'html') {
    return (
      <svg
        viewBox="0 0 24 24"
        className={cn('h-4 w-4', className)}
        aria-hidden="true"
      >
        <path
          d="m8.5 8.5-3 3 3 3M15.5 8.5l3 3-3 3M13.5 7l-3 10"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    )
  }

  return (
    <svg
      viewBox="0 0 24 24"
      className={cn('h-4 w-4', className)}
      aria-hidden="true"
    >
      <rect
        x="6"
        y="4.5"
        width="12"
        height="15"
        rx="2.5"
        fill="currentColor"
        opacity="0.12"
      />
      <path
        d="M9 9h6M9 12.5h6M9 16h4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}
