import { forwardRef, type SVGProps } from 'react'

import { cn } from '@/lib/utils'

export type PlatformIconProps = {
  size?: number | string
  absoluteStrokeWidth?: boolean
  appearance?: 'monochrome' | 'color'
} & SVGProps<SVGSVGElement>

export type PlatformIcon = ReturnType<typeof createPlatformIcon>

/** All glyphs inherit the surrounding semantic color and preserve SVG/ref props. */
export function createPlatformIcon(
  name: string,
  geometry: React.ReactNode,
  colored?: { tone: string; fill: React.ReactNode },
) {
  const Icon = forwardRef<SVGSVGElement, PlatformIconProps>(function PlatformGlyph(
    {
      size = 24,
      strokeWidth = 1.7,
      absoluteStrokeWidth = false,
      appearance = 'monochrome',
      className,
      children,
      ...props
    },
    ref,
  ) {
    const hasAccessibleName = Boolean(props['aria-label']?.trim() || props['aria-labelledby']?.trim())
    const coloredIcon = appearance === 'color' ? colored : undefined
    let renderedStrokeWidth = strokeWidth
    if (absoluteStrokeWidth) {
      const numericSize = Number(size)
      const scale = Number.isFinite(numericSize) && numericSize > 0 ? numericSize : 24
      renderedStrokeWidth = (Number(strokeWidth) * 24) / scale
    }

    return (
      <svg
        ref={ref}
        xmlns="http://www.w3.org/2000/svg"
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={renderedStrokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        focusable="false"
        role={hasAccessibleName ? 'img' : undefined}
        aria-hidden={hasAccessibleName ? undefined : true}
        data-platform-icon={name}
        data-icon-appearance={coloredIcon === undefined ? undefined : 'color'}
        data-icon-tone={coloredIcon?.tone}
        className={cn('shrink-0', className)}
        {...props}
      >
        {coloredIcon !== undefined && (
          <g data-icon-fill="true" opacity="0.12" stroke="none">
            {coloredIcon.fill}
          </g>
        )}
        {geometry}
        {children}
      </svg>
    )
  })
  Icon.displayName = name
  return Icon
}
