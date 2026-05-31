'use client'

import type { CSSProperties } from 'react'

import { cn } from '@/lib/utils'

const ORB_SPECS = [
  {
    left: '14%',
    delay: '0s',
    background: 'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(204,254,255,0.98) 70%, rgba(170,233,242,0.98) 100%)',
  },
  {
    left: '41%',
    delay: '0.14s',
    background: 'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(226,255,212,0.96) 72%, rgba(208,242,214,0.98) 100%)',
  },
  {
    left: '68%',
    delay: '0.28s',
    background: 'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(236,243,255,0.98) 74%, rgba(212,226,255,0.98) 100%)',
  },
] as const

type GraphLoadingIndicatorProps = Readonly<{
  className?: string
  message?: string
  srMessage?: string
  hint?: string
}>

export function GraphLoadingIndicator({
  className,
  message = '正在加载图谱...',
  srMessage = 'Loading graph',
  hint,
}: GraphLoadingIndicatorProps) {
  return (
    <div role="status" aria-live="polite" className={cn('flex flex-col items-center justify-center gap-3 text-center', className)}>
      <div className="graph-loader-stage relative h-[72px] w-[122px]" aria-hidden="true">
        {ORB_SPECS.map((orb) => {
          const orbStyle: CSSProperties = {
            left: orb.left,
            animationDelay: orb.delay,
            background: orb.background,
          }
          const shadowStyle: CSSProperties = {
            left: orb.left,
            animationDelay: orb.delay,
          }

          return (
            <div key={`orb-${orb.left}-${orb.delay}`} className="contents">
              <span className="graph-loader-orb" style={orbStyle} />
              <span className="graph-loader-shadow" style={shadowStyle} />
            </div>
          )
        })}
      </div>

      <div className="space-y-1">
        <p className="text-sm font-medium tracking-[0.01em] text-foreground/88">{message}</p>
        {hint ? (
          <p className="text-[11px] leading-5 text-muted-foreground">{hint}</p>
        ) : null}
      </div>

      <span className="sr-only">{srMessage}</span>

      <style jsx>{`
        .graph-loader-stage {
          filter: drop-shadow(0 14px 22px rgba(98, 118, 122, 0.08));
        }

        .graph-loader-orb {
          position: absolute;
          bottom: 18px;
          width: 18px;
          height: 18px;
          border-radius: 999px;
          transform-origin: 50% 100%;
          box-shadow:
            0 8px 18px rgba(135, 168, 173, 0.2),
            inset 0 1px 0 rgba(255, 255, 255, 0.9),
            inset 0 -2px 6px rgba(125, 186, 191, 0.15);
          will-change: transform, border-radius;
          animation: graph-loader-orb 0.72s infinite alternate cubic-bezier(0.34, 0, 0.2, 1);
        }

        .graph-loader-orb::after {
          content: '';
          position: absolute;
          top: 2px;
          left: 3px;
          width: 58%;
          height: 34%;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.56);
          filter: blur(0.2px);
        }

        .graph-loader-shadow {
          position: absolute;
          bottom: 8px;
          width: 18px;
          height: 5px;
          border-radius: 999px;
          background: radial-gradient(circle at center, rgba(105, 117, 120, 0.22) 0%, rgba(105, 117, 120, 0.08) 62%, rgba(105, 117, 120, 0) 100%);
          filter: blur(1.4px);
          will-change: transform, opacity;
          animation: graph-loader-shadow 0.72s infinite alternate cubic-bezier(0.34, 0, 0.2, 1);
        }

        @keyframes graph-loader-orb {
          0% {
            transform: translateY(16px) scaleX(1.56) scaleY(0.46);
            border-radius: 999px 999px 420px 420px;
          }

          42% {
            transform: translateY(2px) scaleX(1) scaleY(1);
            border-radius: 999px;
          }

          100% {
            transform: translateY(-32px) scaleX(1) scaleY(1);
            border-radius: 999px;
          }
        }

        @keyframes graph-loader-shadow {
          0% {
            transform: scaleX(1.45);
            opacity: 0.22;
          }

          42% {
            transform: scaleX(1);
            opacity: 0.12;
          }

          100% {
            transform: scaleX(0.32);
            opacity: 0.05;
          }
        }

        @media (prefers-reduced-motion: reduce) {
          .graph-loader-orb,
          .graph-loader-shadow {
            animation: none;
          }

          .graph-loader-orb {
            transform: translateY(-10px);
          }

          .graph-loader-shadow {
            opacity: 0.12;
          }
        }
      `}</style>
    </div>
  )
}
