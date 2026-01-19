"use client"

import React from "react"
import Lottie, { LottieComponentProps } from "lottie-react"
import { cn } from "@/lib/utils"

export const LOTTIE_URLS = {
    EMPTY_DOCUMENTS: "https://assets9.lottiefiles.com/packages/lf20_w51pcehl.json", // Placeholder
    THINKING: "https://assets10.lottiefiles.com/packages/lf20_p8bfn5to.json", // Placeholder
    PROCESSING: "https://assets7.lottiefiles.com/packages/lf20_t9qk3z4w.json", // Placeholder
}

interface LottieAnimationProps extends Omit<LottieComponentProps, "animationData"> {
    url: string
    className?: string
}

export function LottieAnimation({ url, className, ...props }: LottieAnimationProps) {
    const [animationData, setAnimationData] = React.useState<any>(null)

    React.useEffect(() => {
        fetch(url)
            .then(res => {
                if (!res.ok) throw new Error('Network response was not ok')
                return res.json()
            })
            .then(data => setAnimationData(data))
            .catch(err => console.error("Failed to load Lottie animation", err))
    }, [url])

    if (!animationData) return <div className={cn("bg-muted/10 animate-pulse rounded-lg", className)} />

    return (
        <div className={className}>
            <Lottie animationData={animationData} {...props} />
        </div>
    )
}
