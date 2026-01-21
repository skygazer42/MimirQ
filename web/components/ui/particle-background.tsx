"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Particles from "react-tsparticles"
import { loadSlim } from "tsparticles-slim"
import type { Engine, IOptions, RecursivePartial } from "tsparticles-engine"
import { useTheme } from "next-themes"
import { useReducedMotion } from "framer-motion"
import { cn } from "@/lib/utils"

type ParticleBackgroundProps = {
  className?: string
  interactive?: boolean
}

export function ParticleBackground({ className, interactive = true }: ParticleBackgroundProps) {
  const { resolvedTheme } = useTheme()
  const shouldReduceMotion = useReducedMotion()
  const [isFinePointer, setIsFinePointer] = useState(false)
  
  const particlesInit = useCallback(async (engine: Engine) => {
    await loadSlim(engine)
  }, [])

  // Disable particles on touch devices and in reduced motion mode.
  useEffect(() => {
    if (typeof window === "undefined") return
    try {
      setIsFinePointer(window.matchMedia("(pointer: fine)").matches)
    } catch {
      setIsFinePointer(true)
    }
  }, [])

  // Dark mode vs Light mode colors
  const isDark = resolvedTheme === "dark"
  const color = isDark ? "#ffffff" : "#0ea5e9" // White in dark, Sky-500 in light
  const linkColor = isDark ? "#ffffff" : "#0284c7" // Sky-600 in light

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

  if (shouldReduceMotion || !isFinePointer) return null

  return (
    <Particles
      id="tsparticles"
      init={particlesInit}
      className={cn("absolute inset-0 -z-10", className)}
      options={options}
    />
  )
}
