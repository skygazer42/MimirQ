"use client"

import { useEffect, useRef, useState } from "react"
import { X, Mic, MicOff } from "lucide-react"
import { motion, AnimatePresence, useReducedMotion } from "framer-motion"
import { Button } from "@/components/ui/button"

interface VoiceModeOverlayProps {
    isOpen: boolean
    onClose: () => void
    onSend: (text: string) => void
}

type SpeechRecognitionResultItem = {
    readonly transcript: string
}

type SpeechRecognitionResultLike = {
    readonly isFinal: boolean
    readonly 0: SpeechRecognitionResultItem
}

type SpeechRecognitionEventLike = {
    readonly resultIndex: number
    readonly results: {
        readonly length: number
        readonly [index: number]: SpeechRecognitionResultLike
    }
}

type SpeechRecognitionLike = {
    continuous: boolean
    interimResults: boolean
    lang: string
    onresult: ((event: SpeechRecognitionEventLike) => void) | null
    start: () => void
    stop: () => void
}

type WindowWithSpeechRecognition = Window & {
    webkitSpeechRecognition?: new () => SpeechRecognitionLike
}

export function VoiceModeOverlay({ isOpen, onClose, onSend }: Readonly<VoiceModeOverlayProps>) {
	    const [isListening, setIsListening] = useState(false)
	    const [transcript, setTranscript] = useState("")
	    const canvasRef = useRef<HTMLCanvasElement>(null)
	    const reduceMotion = useReducedMotion()

    // Speech Recognition Setup
    const recognitionRef = useRef<SpeechRecognitionLike | null>(null)

    useEffect(() => {
        const windowWithSpeech = globalThis.window as WindowWithSpeechRecognition
        if (globalThis.window !== undefined && windowWithSpeech.webkitSpeechRecognition) {
            const SpeechRecognition = windowWithSpeech.webkitSpeechRecognition
            const recognition = new SpeechRecognition()
            recognition.continuous = true
            recognition.interimResults = true
            recognition.lang = 'zh-CN'

            recognition.onresult = (event) => {
                let finalTranscript = ''
                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript
                    }
                }
                if (finalTranscript) {
                    setTranscript(finalTranscript)
                    // Auto send on final result (simple logic)
                    // onSend(finalTranscript)
                }
            }

            recognitionRef.current = recognition
        }
    }, [onSend])

	    // Canvas Animation
	    useEffect(() => {
	        if (!isOpen || !canvasRef.current) return

	        const canvas = canvasRef.current
	        const ctx = canvas.getContext('2d')
	        if (!ctx) return

	        let animationFrameId: number | null = null
	        let phase = 0
	        let viewport = { width: 0, height: 0 }

	        const root = document.documentElement
	        const styles = getComputedStyle(root)
	        const bgVar = styles.getPropertyValue('--background').trim()
	        const fgVar = styles.getPropertyValue('--foreground').trim()
	        const primaryVar = styles.getPropertyValue('--primary').trim()

	        const bgColor = bgVar ? `hsl(${bgVar})` : '#000'
	        const fgColor = fgVar ? `hsl(${fgVar} / 0.75)` : '#ffffff'
	        const primaryColor = primaryVar ? `hsl(${primaryVar})` : '#0ea5e9'
	        const primaryColorMuted = primaryVar ? `hsl(${primaryVar} / 0.3)` : 'rgba(14, 165, 233, 0.3)'

	        const syncCanvasSize = () => {
	            const dpr = Math.max(1, globalThis.window.devicePixelRatio || 1)
	            const width = globalThis.window.innerWidth
	            const height = globalThis.window.innerHeight
	            viewport = { width, height }

	            // Render in CSS pixels, but keep the backing store crisp on HiDPI.
	            canvas.width = Math.round(width * dpr)
	            canvas.height = Math.round(height * dpr)
	            ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
	        }

	        const onResize = () => syncCanvasSize()

	        syncCanvasSize()
	        globalThis.window.addEventListener('resize', onResize)

	        const shouldAnimate = () =>
	            !reduceMotion && isListening && document.visibilityState === 'visible'

	        const render = () => {
	            if (shouldAnimate()) phase += 0.1
	            const { width, height } = viewport

	            ctx.fillStyle = bgColor
	            ctx.fillRect(0, 0, width, height)

	            // Draw Wave
	            ctx.beginPath()
	            ctx.lineWidth = 4
	            ctx.strokeStyle = isListening ? primaryColor : fgColor

	            const cy = height / 2
		            const cx = width / 2

		            // Simple circle wave
		            const jitter = isListening && !reduceMotion ? (Math.sin(phase * 1.7) + 1) * 10 : 0
		            const radius = 100 + Math.sin(phase) * 10 + jitter

		            ctx.arc(cx, cy, radius, 0, 2 * Math.PI)
		            ctx.stroke()

	            // Ripple
	            if (isListening) {
	                ctx.beginPath()
	                ctx.strokeStyle = primaryColorMuted
	                ctx.arc(cx, cy, radius + 30, 0, 2 * Math.PI)
	                ctx.stroke()
	            }

	            if (shouldAnimate()) {
	                animationFrameId = globalThis.window.requestAnimationFrame(render)
	            } else {
	                animationFrameId = null
	            }
	        }

	        const onVisibilityChange = () => {
	            if (shouldAnimate()) {
	                if (animationFrameId == null) {
	                    render()
	                }
	                return
	            }

	            if (animationFrameId != null) {
	                globalThis.window.cancelAnimationFrame(animationFrameId)
	                animationFrameId = null
	            }

	            // Ensure we paint a final static frame on hide.
	            render()
	        }

	        document.addEventListener('visibilitychange', onVisibilityChange)
	        render()
	        return () => {
	            globalThis.window.removeEventListener('resize', onResize)
	            document.removeEventListener('visibilitychange', onVisibilityChange)
	            if (animationFrameId != null) {
	                globalThis.window.cancelAnimationFrame(animationFrameId)
	            }
	        }
	    }, [isOpen, isListening, reduceMotion])

    const toggleListening = () => {
        if (isListening) {
            recognitionRef.current?.stop()
            setIsListening(false)
            if (transcript) onSend(transcript)
        } else {
            recognitionRef.current?.start()
            setIsListening(true)
            setTranscript("")
        }
    }

	    if (!isOpen) {
	        return null
	    }

		    return (
	        <AnimatePresence>
	            <motion.div
	                initial={reduceMotion ? false : { opacity: 0 }}
	                animate={{ opacity: 1 }}
	                exit={reduceMotion ? undefined : { opacity: 0 }}
	                className="fixed inset-0 z-100 bg-background text-foreground flex flex-col items-center justify-center"
	            >
		                <div className="absolute inset-0" aria-hidden="true">
		                    <canvas ref={canvasRef} className="absolute inset-0" />
		                </div>

	                <div className="relative z-10 flex flex-col items-center gap-8">
	                    <div className="h-20 flex items-center justify-center">
	                        {transcript && (
	                            <p className="text-foreground/80 text-xl font-medium text-center max-w-xl motion-safe:animate-fade-in-up">
	                                &quot;{transcript}&quot;
	                            </p>
	                        )}
	                    </div>

		                    <div className="flex gap-4">
		                        <Button
		                            size="icon"
		                            className="h-16 w-16 rounded-full glass hover:bg-accent/30 hover:border-primary/30 transition-colors duration-200 motion-reduce:transition-none"
		                            onClick={toggleListening}
		                            aria-label={isListening ? "停止语音输入" : "开始语音输入"}
		                        >
		                            {isListening ? <Mic className="h-8 w-8 text-primary" /> : <MicOff className="h-8 w-8 text-muted-foreground" />}
		                        </Button>
		                        <Button
		                            size="icon"
		                            variant="ghost"
		                            className="h-16 w-16 rounded-full hover:bg-accent/40 text-muted-foreground hover:text-foreground transition-colors duration-200 motion-reduce:transition-none"
		                            onClick={onClose}
		                            aria-label="关闭语音模式"
		                        >
		                            <X className="h-8 w-8" />
		                        </Button>
		                    </div>
	                </div>
	            </motion.div>
	        </AnimatePresence>
	    )
}
