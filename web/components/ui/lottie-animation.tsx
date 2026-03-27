"use client"

import React from "react"
import Lottie, { LottieComponentProps } from "lottie-react"
import { useReducedMotion } from "framer-motion"
import { cn } from "@/lib/utils"

export const LOTTIE_URLS = {
    EMPTY_DOCUMENTS: "/lottie/empty-documents.json",
    THINKING: "/lottie/thinking.json",
    PROCESSING: "/lottie/processing.json",
}

interface LottieAnimationProps extends Omit<LottieComponentProps, "animationData"> {
    url: string
    className?: string
    fallback?: React.ReactNode
}

const lottieCache = new Map<string, any>()

export function LottieAnimation({ url, className, fallback, ...props }: Readonly<LottieAnimationProps>) {
    const shouldReduceMotion = useReducedMotion()
    const [animationData, setAnimationData] = React.useState<any>(() => lottieCache.get(url) ?? null)
    const [hasError, setHasError] = React.useState(false)

    React.useEffect(() => {
        if (!url) return
        if (lottieCache.has(url)) {
            setAnimationData(lottieCache.get(url))
            return
        }

        const controller = new AbortController()
        let alive = true

        setHasError(false)
        fetch(url, { signal: controller.signal })
            .then((res) => {
                if (!res.ok) throw new Error("Network response was not ok")
                return res.json()
            })
            .then((data) => {
                if (!alive) return
                lottieCache.set(url, data)
                setAnimationData(data)
            })
            .catch((err) => {
                if (!alive) return
                if (err?.name === "AbortError") return
                setHasError(true)
                console.error("Failed to load Lottie animation", err)
            })

        return () => {
            alive = false
            controller.abort()
        }
    }, [url])

    if (shouldReduceMotion) {
        return fallback ? (
            <>{fallback}</>
        ) : (
            <div aria-hidden="true" className={cn("bg-muted/10 rounded-lg", className)} />
        )
    }

    if (!animationData || hasError) {
        return fallback ? (
            <>{fallback}</>
        ) : (
            <div
                aria-hidden="true"
                className={cn("bg-muted/10 animate-pulse motion-reduce:animate-none rounded-lg", className)}
            />
        )
    }

    return (
        <div className={className}>
            <Lottie animationData={animationData} {...props} />
        </div>
    )
}
