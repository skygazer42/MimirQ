'use client'

import Image from 'next/image'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { ComponentProps, CSSProperties } from 'react'

import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { fetchAuthAssetUrl, normalizeAssetUrl, invalidateAuthAssetUrl } from '@/lib/image-auth-proxy'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

type AuthImageProps = Omit<ComponentProps<typeof Image>, 'src'> & { src?: string | null }

type AuthImageLinkProps = Readonly<{
  src: string
  alt: string
  className?: string
  title?: string
}>

type AuthImageFeedbackStyle = CSSProperties & {
  '--auth-image-width'?: string
  '--auth-image-height'?: string
}

type AuthAssetState =
  | Readonly<{ status: 'idle' }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{ status: 'ready'; url: string }>
  | Readonly<{ status: 'error'; message: string }>

type AuthAssetResult = Readonly<{
  source: string
  scope: string
  requestRevision: number
  failedUrl?: string
  state: Extract<AuthAssetState, { status: 'ready' | 'error' }>
}>

export function useAuthAsset(
  src: string | null | undefined,
  { enabled = true }: Readonly<{ enabled?: boolean }> = {},
): Readonly<{ state: AuthAssetState; retry: () => void; reportImageError: (url: string) => void }> {
  const source = normalizeAssetUrl(src)
  const scope = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const [requestRevision, setRequestRevision] = useState(0)
  const [result, setResult] = useState<AuthAssetResult | null>(null)
  const retry = useCallback(() => {
    if (
      result?.source === source &&
      result.scope === scope &&
      result.requestRevision === requestRevision &&
      result.failedUrl !== undefined
    )
      invalidateAuthAssetUrl(result.failedUrl, scope)
    setRequestRevision((revision) => revision + 1)
  }, [result, source, scope, requestRevision])

  const reportImageError = useCallback(
    (url: string) => {
      setResult((previous) => {
        if (
          previous === null ||
          previous.source !== source ||
          previous.scope !== scope ||
          previous.requestRevision !== requestRevision ||
          previous.state.status !== 'ready' ||
          previous.state.url !== url
        )
          return previous
        return { ...previous, failedUrl: url, state: { status: 'error', message: '图片无法显示' } }
      })
    },
    [source, scope, requestRevision],
  )

  useEffect(() => {
    if (!enabled || source === null) return
    let current = true
    void fetchAuthAssetUrl(source).then(
      (url) => {
        if (current) setResult({ source, scope, requestRevision, state: { status: 'ready', url } })
      },
      (error: unknown) => {
        if (!current) return
        const message = error instanceof Error ? error.message : String(error)
        setResult({ source, scope, requestRevision, state: { status: 'error', message } })
      },
    )
    return () => {
      current = false
    }
  }, [enabled, source, scope, requestRevision])

  if (!enabled || source === null) return { state: { status: 'idle' }, retry, reportImageError }
  const state: AuthAssetState =
    result?.source === source && result.scope === scope && result.requestRevision === requestRevision
      ? result.state
      : { status: 'loading' }
  return { state, retry, reportImageError }
}

function AssetFeedback({
  state,
  label,
  className,
  style,
  onRetry,
}: Readonly<{
  state: Extract<AuthAssetState, { status: 'idle' | 'loading' | 'error' }>
  label: string
  className?: string
  style?: CSSProperties
  onRetry: () => void
}>) {
  const containerRef = useRef<HTMLSpanElement | null>(null)
  const [canShowRetry, setCanShowRetry] = useState(false)
  useLayoutEffect(() => {
    const container = containerRef.current
    if (container === null) return
    const action = container.closest('button, a')
    setCanShowRetry(action === null)
    if (state.status !== 'error' || action === null) return
    action.addEventListener('click', onRetry)
    return () => action.removeEventListener('click', onRetry)
  }, [state.status, onRetry])
  if (state.status === 'idle') return null
  if (state.status === 'loading') {
    return (
      <span
        ref={containerRef}
        role="status"
        aria-label="正在加载图片"
        className={cn('inline-block overflow-hidden', className)}
        style={style}
      >
        <Skeleton asChild className="block h-full min-h-8 w-full rounded-none">
          <span />
        </Skeleton>
      </span>
    )
  }
  return (
    <span ref={containerRef} className={cn('inline-block bg-muted/40', className, 'overflow-auto')} style={style}>
      <span className="flex min-h-full w-full flex-col items-start justify-center gap-2 p-2 text-xs">
        <span role="alert" className="break-words text-muted-foreground">
          {label}加载失败：{state.message}
        </span>
        {canShowRetry ? (
          <Button type="button" variant="outline" size="sm" onClick={onRetry}>
            重试
          </Button>
        ) : null}
      </span>
    </span>
  )
}

export function AuthImage({
  src,
  alt,
  className,
  style,
  fill,
  width,
  height,
  onError,
  ...props
}: Readonly<AuthImageProps>) {
  const { state, retry, reportImageError } = useAuthAsset(src)
  if (state.status === 'ready') {
    return (
      <Image
        {...props}
        src={state.url}
        alt={alt}
        className={className}
        style={style}
        fill={fill}
        width={width}
        height={height}
        onError={(event) => {
          reportImageError(state.url)
          onError?.(event)
        }}
      />
    )
  }
  const feedbackStyle: AuthImageFeedbackStyle = {
    '--auth-image-width': width === undefined ? undefined : width + 'px',
    '--auth-image-height': height === undefined ? undefined : height + 'px',
    aspectRatio: width === undefined || height === undefined ? undefined : [width, height].join(' / '),
    ...(fill ? { position: 'absolute', inset: 0, width: '100%', height: '100%' } : {}),
    ...style,
  }
  return (
    <AssetFeedback
      state={state}
      label={alt}
      onRetry={retry}
      style={feedbackStyle}
      className={cn('w-[var(--auth-image-width)] h-[var(--auth-image-height)]', className)}
    />
  )
}

export function AuthImageLink({ src, alt, className, title }: AuthImageLinkProps) {
  const { state, retry, reportImageError } = useAuthAsset(src)
  const frameClassName = cn('relative block h-32 w-48 overflow-hidden rounded-md border border-border', className)
  if (state.status !== 'ready') {
    return <AssetFeedback state={state} label={alt} className={frameClassName} onRetry={retry} />
  }
  return (
    <a href={state.url} target="_blank" rel="noopener noreferrer" className={frameClassName} title={title}>
      <Image
        src={state.url}
        alt={alt}
        fill
        unoptimized
        sizes="192px"
        className="object-contain"
        onError={() => reportImageError(state.url)}
      />
    </a>
  )
}
