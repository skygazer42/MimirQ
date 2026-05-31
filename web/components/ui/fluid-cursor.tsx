"use client"

import { useEffect, useState } from "react"
import { motion, useMotionValue, useReducedMotion, useSpring } from "framer-motion"
import { usePathname } from "@/i18n/navigation"

import { cn } from "@/lib/utils"

export function FluidCursor() {
  const enabled = process.env.NEXT_PUBLIC_ENABLE_FLUID_CURSOR === "1"

  const [variant, setVariant] = useState<"default" | "pointer" | "text" | "hidden">("default")
  const cursorX = useMotionValue(-100)
  const cursorY = useMotionValue(-100)
  const shouldReduceMotion = useReducedMotion()

  // Slower spring for "follower" effect
  const springConfig = { damping: 25, stiffness: 300 }
  const cursorXSpring = useSpring(cursorX, springConfig)
  const cursorYSpring = useSpring(cursorY, springConfig)

  const pathname = usePathname()

  // Only render/attach listeners on desktop pointers.
  const [isDesktop, setIsDesktop] = useState(false)
  useEffect(() => {
    if (!enabled) return
    if (globalThis.window === undefined) return
    const mq = globalThis.window.matchMedia("(pointer: fine)")
    const update = () => setIsDesktop(mq.matches)
    update()

    // Keep in sync on hybrid devices / pointer changes.
    mq.addEventListener("change", update)
    return () => mq.removeEventListener("change", update)
  }, [enabled])

  useEffect(() => {
    if (!enabled) return
    if (shouldReduceMotion) return
    if (!isDesktop) return
    // IMPORTANT: Do NOT hide default cursor. User feedback indicated visibility issues.
    // document.body.style.cursor = 'none' 

    // Add class to body to indicate custom cursor active (optional, for other CSS hooks if needed)
    document.body.classList.add('custom-cursor-enabled')

    const moveCursor = (e: MouseEvent) => {
      // Keep the cursor centered; ring size is stable and we only animate transform/opacity.
      cursorX.set(e.clientX - 16)
      cursorY.set(e.clientY - 16)
    }

    const checkHover = (e: MouseEvent) => {
      const target = e.target as HTMLElement

      // Check for buttons/links
      const isClickable = target.closest('button') || target.closest('a') || target.closest('[role="button"]')
      // Check for inputs/textareas
      const isInput = target.closest('input') || target.closest('textarea') || target.closest('[contenteditable="true"]')

      if (isInput) {
        setVariant("text")
      } else if (isClickable) {
        setVariant("pointer")
      } else {
        setVariant("default")
      }
    }

    const handleMouseLeave = () => setVariant("hidden")
    const handleMouseEnter = () => setVariant("default")

    globalThis.window.addEventListener("mousemove", moveCursor)
    globalThis.window.addEventListener("mouseover", checkHover)
    document.addEventListener("mouseleave", handleMouseLeave)
    document.addEventListener("mouseenter", handleMouseEnter)

    return () => {
      globalThis.window.removeEventListener("mousemove", moveCursor)
      globalThis.window.removeEventListener("mouseover", checkHover)
      document.removeEventListener("mouseleave", handleMouseLeave)
      document.removeEventListener("mouseenter", handleMouseEnter)
      // Ensure specific style cleanups
      document.body.style.cursor = ''
      document.body.classList.remove('custom-cursor-enabled')
    }
  }, [enabled, pathname, cursorX, cursorY, isDesktop, shouldReduceMotion])

  // Variants for Framer Motion
  const variants = {
    default: {
      scale: 1,
      opacity: 0.5,
    },
    pointer: {
      scale: 1.5,
      opacity: 0.8,
    },
    text: {
      scale: 1,
      opacity: 0.5,
    },
    hidden: {
      scale: 0.8,
      opacity: 0
    }
  }

  if (!enabled || shouldReduceMotion || !isDesktop) return null

  const appearance = variant === "hidden" ? "default" : variant

  return (
    <motion.div
      className={cn(
        "fixed top-0 left-0 z-90 pointer-events-none size-8 rounded-full border-2 border-primary",
        appearance === "pointer" && "bg-primary/10 border-solid",
        appearance === "default" && "bg-transparent border-solid",
        appearance === "text" && "bg-transparent border-dashed"
      )}
      aria-hidden="true"
      style={{
        translateX: cursorXSpring,
        translateY: cursorYSpring,
        // Keep the cursor opt-in to normal blending; avoids weird contrast inversions on rich content.
        mixBlendMode: "normal",
      }}
      variants={variants}
      animate={variant}
      transition={{ type: "spring", stiffness: 500, damping: 28 }}
    />
  )
}
