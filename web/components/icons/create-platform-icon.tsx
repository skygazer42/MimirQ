import { forwardRef, type SVGProps } from 'react'

import { cn } from '@/lib/utils'

export interface PlatformIconProps extends SVGProps<SVGSVGElement> {
  size?: number | string
  absoluteStrokeWidth?: boolean
  appearance?: 'monochrome' | 'color'
}

export type PlatformIcon = ReturnType<typeof createPlatformIcon>

/** All glyphs inherit the surrounding semantic color and preserve SVG/ref props. */
export function createPlatformIcon(
  name: string,
  geometry: React.ReactNode,
  colored?: { tone: string; fill: React.ReactNode },
) {
  const Icon = forwardRef<SVGSVGElement, PlatformIconProps>(function PlatformGlyph(
    { size = 24, strokeWidth = 1.7, absoluteStrokeWidth = false, appearance = 'monochrome', className, children, ...props },
    ref,
  ) {
    const named = Boolean(props['aria-label'] || props['aria-labelledby'])

    return (
      <svg
        ref={ref}
        xmlns="http://www.w3.org/2000/svg"
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={absoluteStrokeWidth ? Number(strokeWidth) * 24 / (Number(size) || 24) : strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        focusable="false"
        role={named ? 'img' : undefined}
        aria-hidden={named ? undefined : true}
        data-platform-icon={name}
        data-icon-appearance={colored && appearance === 'color' ? 'color' : undefined}
        data-icon-tone={colored && appearance === 'color' ? colored.tone : undefined}
        className={cn('shrink-0', className)}
        {...props}
      >
        {colored && appearance === 'color' ? (
          <g data-icon-fill="true" opacity="0.12" stroke="none">{colored.fill}</g>
        ) : null}
        {geometry}
        {children}
      </svg>
    )
  })
  Icon.displayName = name
  return Icon
}
