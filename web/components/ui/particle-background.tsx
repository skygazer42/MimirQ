"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Particles from "react-tsparticles"
import { loadSlim } from "tsparticles-slim"
import type { Engine, IOptions, RecursivePartial } from "tsparticles-engine"
import { useTheme } from "next-themes"
import { useReducedMotion } from "framer-motion"
import { cn } from "@/lib/utils"
import { getCssHslColor } from "@/lib/css-vars"

type ParticleBackgroundProps = {
  className?: string
  interactive?: boolean
}

export function ParticleBackground({ className, interactive = true }: ParticleBackgroundProps) {
  const { resolvedTheme } = useTheme()
  const shouldReduceMotion = useReducedMotion()
  const [isFinePointer, setIsFinePointer] = useState(false)
  const [isVisible, setIsVisible] = useState(true)
  
  const particlesInit = useCallback(async (engine: Engine) => {
    await loadSlim(engine)
  }, [])

  // Disable particles on touch devices and in reduced motion mode.
  useEffect(() => {
    if (typeof window === "undefined") return
    const mq = window.matchMedia("(pointer: fine)")
    const update = () => setIsFinePointer(mq.matches)
    update()

    try {
      mq.addEventListener("change", update)
      return () => mq.removeEventListener("change", update)
    } catch {
      // Safari < 14
      mq.addListener(update)
      return () => mq.removeListener(update)
    }
  }, [])

  // Pause/disable when the tab is hidden (keeps background loops from burning CPU).
  useEffect(() => {
    if (typeof document === "undefined") return
    const update = () => setIsVisible(document.visibilityState === "visible")
    update()
    document.addEventListener("visibilitychange", update)
    return () => document.removeEventListener("visibilitychange", update)
  }, [])

  // Token-driven colors (re-evaluated when theme flips).
  // NOTE: the `resolvedTheme` dependency is only used to re-run after theme changes.
  const color = useMemo(() => getCssHslColor("--muted-foreground", "hsl(215, 20%, 65%)"), [resolvedTheme])
  const linkColor = useMemo(() => getCssHslColor("--muted-foreground", "hsl(215, 20%, 65%)"), [resolvedTheme])

  const options = useMemo(
    () =>
      ({
      background: {
        color: { value: "transparent" },
      },
      fpsLimit: 60,
      interactivity: {
        events: {
          onClick: {
            enable: interactive,
            mode: "push",
          },
          onHover: {
            enable: interactive,
            mode: "grab",
          },
          resize: true,
        },
        modes: {
          push: { quantity: 4 },
          repulse: { distance: 200, duration: 0.4 },
          grab: { distance: 140, links: { opacity: 0.5 } },
        },
      },
      particles: {
        color: { value: color },
        links: {
          color: linkColor,
          distance: 150,
          enable: true,
          opacity: 0.2,
          width: 1,
        },
        move: {
          direction: "none",
          enable: true,
          outModes: { default: "bounce" },
          random: false,
          speed: 1,
          straight: false,
        },
        number: {
          density: { enable: true, area: 800 },
          value: 70,
        },
        opacity: { value: 0.3 },
        shape: { type: "circle" },
        size: { value: { min: 1, max: 3 } },
      },
      detectRetina: true,
    } as const satisfies RecursivePartial<IOptions>),
    [color, interactive, linkColor]
  )

  if (shouldReduceMotion || !isFinePointer || !isVisible) return null

  return (
    <Particles
      id="tsparticles"
      init={particlesInit}
      className={cn("absolute inset-0 -z-10", className)}
      options={options}
    />
  )
}
