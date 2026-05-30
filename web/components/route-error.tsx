'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { useTranslations } from 'next-intl'

import { FullScreenFrame } from '@/components/full-screen-frame'
import { extractRequestIdFromError } from '@/lib/api-errors'
import { captureApiError } from '@/lib/api-error-reporting'
import { reloadOnceForStaleChunk } from '@/lib/stale-chunk-recovery'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type RouteErrorProps = Readonly<{
  error: Error & { digest?: string }
  reset: () => void
  title?: string
  message?: string
  href?: string
  hrefLabel?: string
  fullScreen?: boolean
}>

function retryRouteAfterBoundaryError(reset: () => void) {
  reset()
  if (globalThis.window === undefined) return
  globalThis.window.location.reload()
}

function DisconnectedCloudIllustration() {
  return (
    <svg
      aria-hidden="true"
      className="h-[230px] w-[330px] drop-shadow-[0_32px_42px_rgba(105,124,166,0.18)] sm:h-[300px] sm:w-[430px]"
      viewBox="0 0 430 310"
      fill="none"
    >
      <defs>
        <linearGradient id="route-error-cloud" x1="115" x2="330" y1="84" y2="214">
          <stop stopColor="hsl(var(--warning) / 0.26)" />
          <stop offset="0.55" stopColor="hsl(var(--card) / 0.94)" />
          <stop offset="1" stopColor="hsl(var(--accent) / 0.18)" />
        </linearGradient>
        <linearGradient id="route-error-planet" x1="275" x2="365" y1="30" y2="118">
          <stop stopColor="hsl(var(--primary) / 0.22)" />
          <stop offset="1" stopColor="hsl(var(--info) / 0.42)" />
        </linearGradient>
        <linearGradient id="route-error-button-mark" x1="318" x2="376" y1="155" y2="213">
          <stop stopColor="hsl(var(--warning))" />
          <stop offset="1" stopColor="hsl(var(--destructive))" />
        </linearGradient>
      </defs>

      <circle cx="182" cy="102" r="74" fill="hsl(var(--warning))" opacity="0.16" />
      <circle cx="292" cy="72" r="54" fill="url(#route-error-planet)" opacity="0.58" />
      <circle cx="265" cy="217" r="83" fill="hsl(var(--accent))" opacity="0.12" />
      <circle cx="336" cy="150" r="42" fill="hsl(var(--card))" opacity="0.7" />
      <circle cx="92" cy="150" r="20" fill="hsl(var(--primary))" opacity="0.16" />
      <circle cx="126" cy="68" r="7" fill="hsl(var(--warning))" />
      <circle cx="382" cy="89" r="8" fill="hsl(var(--muted-foreground))" opacity="0.34" />

      <path
        d="M286 34c18 8 33 24 40 43M292 35c-11 25-14 55-8 84M253 63c29 6 58 19 82 39M252 102c27 8 56 14 89 14"
        stroke="hsl(var(--primary))"
        strokeLinecap="round"
        strokeWidth="5"
        opacity="0.28"
      />

      <path
        d="M117 182h210c24 0 43-19 43-43 0-22-16-40-37-43-7-31-35-54-68-54-29 0-54 17-65 42-10-9-24-14-39-14-31 0-57 24-60 55-25 5-44 28-44 55 0 1 0 2 .1 2H117Z"
        fill="url(#route-error-cloud)"
        opacity="0.94"
      />
      <path
        d="M117 182h210c24 0 43-19 43-43 0-22-16-40-37-43-7-31-35-54-68-54-29 0-54 17-65 42-10-9-24-14-39-14-31 0-57 24-60 55-25 5-44 28-44 55 0 1 0 2 .1 2H117Z"
        stroke="hsl(var(--primary) / 0.34)"
        strokeLinejoin="round"
        strokeWidth="5"
      />
      <path
        d="M276 60c18 4 33 16 42 33M323 103c3 5 5 11 6 17"
        stroke="hsl(var(--primary) / 0.36)"
        strokeLinecap="round"
        strokeWidth="5"
        opacity="0.74"
      />

      <circle cx="202" cy="122" r="9" fill="hsl(var(--foreground))" />
      <circle cx="274" cy="122" r="9" fill="hsl(var(--foreground))" />
      <path d="M224 150c11-12 27-12 38 0" stroke="hsl(var(--foreground))" strokeLinecap="round" strokeWidth="6" />
      <ellipse cx="171" cy="140" fill="hsl(var(--destructive))" opacity="0.34" rx="17" ry="8" />
      <ellipse cx="301" cy="140" fill="hsl(var(--destructive))" opacity="0.34" rx="17" ry="8" />

      <circle cx="335" cy="185" r="32" fill="url(#route-error-button-mark)" />
      <path d="m322 172 26 26M348 172l-26 26" stroke="white" strokeLinecap="round" strokeWidth="7" />

      <path
        d="M160 221c-28 3-47 17-63 43"
        stroke="hsl(var(--primary))"
        strokeLinecap="round"
        strokeWidth="8"
        opacity="0.64"
      />
      <path
        d="M285 229c26 6 48 17 67 31"
        stroke="hsl(var(--primary))"
        strokeLinecap="round"
        strokeWidth="8"
        opacity="0.64"
      />
      <path
        d="m170 158-25 58 26 11 25-58-26-11Z"
        fill="hsl(var(--primary) / 0.42)"
        stroke="hsl(var(--primary) / 0.58)"
        strokeLinejoin="round"
        strokeWidth="4"
      />
      <path d="M166 162h-8M178 167h-8" stroke="hsl(var(--primary-foreground))" strokeLinecap="round" strokeWidth="4" />
      <path
        d="m288 216-10 31 56 18 10-31-56-18Z"
        fill="hsl(var(--primary) / 0.42)"
        stroke="hsl(var(--primary) / 0.58)"
        strokeLinejoin="round"
        strokeWidth="4"
      />
      <path d="M237 225v12M221 217l-11 6M224 241l-11 6" stroke="hsl(var(--warning))" strokeLinecap="round" strokeWidth="5" />
    </svg>
  )
}

function RouteErrorScene({
  error,
  reset,
  title,
  message,
  href = '/',
  hrefLabel,
  fullScreen = false,
}: RouteErrorProps) {
  const t = useTranslations('RouteBoundaries')
  const requestId = extractRequestIdFromError(error)
  const resolvedTitle = title ?? t("error.title")
  const resolvedMessage = message ?? t("error.message")
  const resolvedHrefLabel = hrefLabel ?? t("error.home")

  useEffect(() => {
    if (reloadOnceForStaleChunk(error)) return
    captureApiError(error, resolvedMessage, { tags: { boundary: 'route-error' } })
  }, [error, resolvedMessage])

  return (
    <section
      className={cn(
        'relative isolate flex w-full flex-1 items-center justify-center overflow-hidden bg-background px-6 py-14 text-foreground transition-colors duration-200',
        fullScreen ? 'min-h-dvh' : 'min-h-[560px] rounded-[2rem]'
      )}
      style={{
        background:
          'radial-gradient(circle at 50% 30%, hsl(var(--primary) / 0.10), transparent 28%), radial-gradient(circle at 18% 84%, hsl(var(--accent) / 0.08), transparent 34%), var(--app-background-base)',
      }}
    >
      <div
        aria-hidden="true"
        className="absolute -left-10 bottom-14 h-44 w-64 rotate-[36deg] rounded-[2.2rem] border border-border/55"
      />
      <div
        aria-hidden="true"
        className="absolute -left-5 bottom-3 h-36 w-56 rotate-[42deg] rounded-[2.2rem] border border-border/45"
      />
      <div
        aria-hidden="true"
        className="absolute right-[7%] top-[18%] h-28 w-28 rotate-45 rounded-[1.6rem] border border-border/50"
      />
      <div
        aria-hidden="true"
        className="absolute right-[5%] top-[24%] h-32 w-px -rotate-[28deg] bg-border/65"
      />
      <div
        aria-hidden="true"
        className="absolute bottom-[5%] right-[3%] h-20 w-20 rounded-full bg-[radial-gradient(circle,hsl(var(--card))_0_16%,transparent_18%)] opacity-80 before:absolute before:left-1/2 before:top-0 before:h-full before:w-px before:-translate-x-1/2 before:bg-card after:absolute after:left-0 after:top-1/2 after:h-px after:w-full after:-translate-y-1/2 after:bg-card"
      />

      <div className="relative z-10 flex w-full max-w-3xl flex-col items-center text-center">
        <DisconnectedCloudIllustration />
        <h1 className="mt-4 text-[clamp(2.45rem,4.8vw,3.35rem)] font-semibold leading-tight tracking-[-0.055em] text-foreground sm:mt-5">
          {resolvedTitle}
        </h1>
        <p className="mt-4 max-w-2xl text-base font-medium leading-8 text-muted-foreground sm:text-xl">
          {resolvedMessage}
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-4 sm:flex-row">
          <Button
            className="h-14 min-w-44 rounded-full border-0 bg-[linear-gradient(180deg,hsl(var(--primary)),hsl(var(--info)))] px-11 text-base font-semibold text-primary-foreground shadow-[0_18px_34px_-18px_hsl(var(--primary)/0.78)] transition-transform duration-200 hover:scale-[1.02] hover:brightness-105 active:scale-[0.98]"
            onClick={() => retryRouteAfterBoundaryError(reset)}
          >
            {t("error.retry")}
          </Button>
          <Button
            variant="outline"
            className="h-14 min-w-44 rounded-full border-border/70 bg-card/35 px-11 text-base font-semibold text-muted-foreground shadow-none backdrop-blur-sm transition-colors duration-200 hover:border-primary/45 hover:bg-card/60 hover:text-foreground"
            asChild
          >
            <Link href={href}>{resolvedHrefLabel}</Link>
          </Button>
        </div>
        <div className="mt-6 space-y-1 text-xs font-mono text-muted-foreground">
          {requestId ? <p>{t("error.requestId", { requestId })}</p> : null}
          {error?.digest ? <p>{t("error.errorId", { errorId: error.digest })}</p> : null}
        </div>
      </div>
    </section>
  )
}

export function RouteError(props: RouteErrorProps) {
  if (props.fullScreen) {
    return (
      <FullScreenFrame
        showBackground={false}
        className="bg-background"
        mainClassName="p-0"
      >
        <RouteErrorScene {...props} fullScreen />
      </FullScreenFrame>
    )
  }

  return (
    <div className="flex flex-1 items-stretch justify-center p-6">
      <RouteErrorScene {...props} />
    </div>
  )
}
