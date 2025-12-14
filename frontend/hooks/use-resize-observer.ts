'use client'

import { useState, useEffect, RefObject } from 'react'

export function useResizeObserver(ref: RefObject<HTMLElement>) {
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })

  useEffect(() => {
    if (!ref.current) return

    const observeTarget = ref.current
    let animationFrameId: number
    let retryCount = 0
    const maxRetries = 20 // Retry for ~2 seconds (assuming ~100ms interval)

    const updateDimensions = () => {
      if (!observeTarget) return
      
      const rect = observeTarget.getBoundingClientRect()
      
      // Only update if dimensions have actually changed and are valid
      if (rect.width > 0 && rect.height > 0) {
        setDimensions(prev => {
           if (prev.width === rect.width && prev.height === rect.height) return prev
           return { width: rect.width, height: rect.height }
        })
      } else if (retryCount < maxRetries) {
         // If dimensions are 0, retry in next frame
         retryCount++
         animationFrameId = requestAnimationFrame(() => setTimeout(updateDimensions, 100))
      }
    }

    // Initial check
    updateDimensions()

    const resizeObserver = new ResizeObserver((entries) => {
      entries.forEach((entry) => {
        const { width, height } = entry.contentRect
        if (width > 0 && height > 0) {
          setDimensions(prev => {
             if (prev.width === width && prev.height === height) return prev
             return { width, height }
          })
        }
      })
    })

    resizeObserver.observe(observeTarget)

    return () => {
      resizeObserver.unobserve(observeTarget)
      if (animationFrameId) cancelAnimationFrame(animationFrameId)
    }
  }, [ref])

  return dimensions
}
