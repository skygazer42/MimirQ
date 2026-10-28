'use client'

import { useEffect, useRef } from 'react'
import Image from 'next/image'
import styles from './auth.module.css'

export function AuthBrandPanel() {
    const backdropRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const backdrop = backdropRef.current
        const scene = backdrop?.parentElement
        if (!backdrop || !scene) return

        const reduce = window.matchMedia('(prefers-reduced-motion: reduce)')
        const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)')
        let frame = 0
        let x = 0
        let y = 0

        const paint = () => {
            frame = 0
            backdrop.style.setProperty('--auth-px', `${x.toFixed(2)}px`)
            backdrop.style.setProperty('--auth-py', `${y.toFixed(2)}px`)
        }
        const reset = () => {
            x = y = 0
            if (frame) cancelAnimationFrame(frame)
            paint()
        }
        const move = (event: PointerEvent) => {
            if (reduce.matches || !finePointer.matches || document.hidden || backdrop.dataset.settled) return
            x = (event.clientX / window.innerWidth - .5) * 16
            y = (event.clientY / window.innerHeight - .5) * 12
            if (!frame) frame = requestAnimationFrame(paint)
        }
        const visibility = () => {
            backdrop.dataset.paused = String(document.hidden)
            if (document.hidden) reset()
        }
        const settle = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return
            backdrop.dataset.settled = 'true'
            reset()
        }

        scene.addEventListener('pointermove', move, { passive: true })
        scene.addEventListener('pointerleave', reset)
        reduce.addEventListener('change', reset)
        document.addEventListener('visibilitychange', visibility)
        document.addEventListener('keydown', settle)
        window.addEventListener('pagehide', reset)
        return () => {
            if (frame) cancelAnimationFrame(frame)
            scene.removeEventListener('pointermove', move)
            scene.removeEventListener('pointerleave', reset)
            reduce.removeEventListener('change', reset)
            document.removeEventListener('visibilitychange', visibility)
            document.removeEventListener('keydown', settle)
            window.removeEventListener('pagehide', reset)
        }
    }, [])

    return (
        <div ref={backdropRef} className={styles.backdrop} aria-hidden="true">
            <picture>
                <source media="(max-width: 620px) and (max-height: 700px)" srcSet="/brand/explorations/ragvia/auth-background-mobile-short.svg" />
                <source media="(max-width: 620px)" srcSet="/brand/explorations/ragvia/auth-background-mobile.svg" />
                <Image
                    src="/brand/explorations/ragvia/auth-background.svg"
                    alt=""
                    width={1280}
                    height={800}
                    className={styles.backdropImage}
                    priority
                    unoptimized
                    draggable={false}
                />
            </picture>
        </div>
    )
}
