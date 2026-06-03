'use client'

import Image from 'next/image'
import { useEffect, useMemo, useState } from 'react'
import type { ComponentProps, MouseEventHandler, ReactNode } from 'react'

import { fetchAuthAssetUrl, needsAuthAssetProxy, normalizeAssetUrl } from '@/lib/image-auth-proxy'

type AuthImageProps = Omit<ComponentProps<typeof Image>, 'src'> & {
  src?: string | null
}

type AuthImageLinkProps = Readonly<{
  src?: string | null
  href?: string | null
  alt?: string
  className?: string
  title?: string
  onClick?: MouseEventHandler<HTMLAnchorElement>
  children: ReactNode
}>

export function useResolvedAuthAssetUrl(
  src?: string | null,
  options?: { enabled?: boolean }
): string | null {
  const enabled = options?.enabled ?? true
  const normalizedSrc = useMemo(() => normalizeAssetUrl(src), [src])
  const [resolvedSrc, setResolvedSrc] = useState<string | null>(() => {
    if (!enabled || !normalizedSrc) return null
    return needsAuthAssetProxy(normalizedSrc) ? null : normalizedSrc
  })

  useEffect(() => {
    let cancelled = false

    if (!enabled || !normalizedSrc) {
      setResolvedSrc(null)
      return
    }

    if (!needsAuthAssetProxy(normalizedSrc)) {
      setResolvedSrc(normalizedSrc)
      return
    }

    setResolvedSrc(null)
    fetchAuthAssetUrl(normalizedSrc)
      .then((nextUrl) => {
        if (!cancelled) setResolvedSrc(nextUrl)
      })
      .catch(() => {
        if (!cancelled) setResolvedSrc(null)
      })

    return () => {
      cancelled = true
    }
  }, [enabled, normalizedSrc])

  return resolvedSrc
}

export function AuthImage({ src, alt, ...props }: AuthImageProps) {
  const resolvedSrc = useResolvedAuthAssetUrl(src)
  if (!resolvedSrc) return null

  return <Image {...props} src={resolvedSrc} alt={alt} />
}

export function AuthImageLink({
  src,
  href,
  alt,
  className,
  title,
  onClick,
  children,
}: AuthImageLinkProps) {
  const resolvedSrc = useResolvedAuthAssetUrl(href ?? src)
  if (!resolvedSrc) return null

  return (
    <a
      href={resolvedSrc}
      target="_blank"
      rel="noopener noreferrer"
      className={className}
      title={title || alt || undefined}
      onClick={onClick}
    >
      {children}
    </a>
  )
}
