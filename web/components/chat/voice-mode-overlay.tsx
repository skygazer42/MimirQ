"use client"

import { useEffect, useRef, useState } from "react"
import { X, Mic, MicOff } from "lucide-react"
import { motion, AnimatePresence } from "framer-motion"
import { Button } from "@/components/ui/button"

interface VoiceModeOverlayProps {
    isOpen: boolean
    onClose: () => void
    onSend: (text: string) => void
}

export function VoiceModeOverlay({ isOpen, onClose, onSend }: VoiceModeOverlayProps) {
    const [isListening, setIsListening] = useState(false)
    const [transcript, setTranscript] = useState("")
    const canvasRef = useRef<HTMLCanvasElement>(null)

    // Speech Recognition Setup
    const recognitionRef = useRef<any>(null)

    useEffect(() => {
        if (typeof window !== 'undefined' && (window as any).webkitSpeechRecognition) {
            const SpeechRecognition = (window as any).webkitSpeechRecognition
            const recognition = new SpeechRecognition()
            recognition.continuous = true
            recognition.interimResults = true
            recognition.lang = 'zh-CN'

            recognition.onresult = (event: any) => {
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

        let animationFrameId: number
        let phase = 0

        const render = () => {
            phase += 0.1
            const width = canvas.width = window.innerWidth
            const height = canvas.height = window.innerHeight

            ctx.fillStyle = '#000000'
            ctx.fillRect(0, 0, width, height)

            // Draw Wave
            ctx.beginPath()
            ctx.lineWidth = 4
            ctx.strokeStyle = isListening ? '#0ea5e9' : '#ffffff'

            const cy = height / 2
            const cx = width / 2

            // Simple circle wave
            const radius = 100 + Math.sin(phase) * 10 + (isListening ? Math.random() * 20 : 0)

            ctx.arc(cx, cy, radius, 0, 2 * Math.PI)
            ctx.stroke()

            // Ripple
            if (isListening) {
                ctx.beginPath()
                ctx.strokeStyle = `rgba(14, 165, 233, 0.3)`
                ctx.arc(cx, cy, radius + 30, 0, 2 * Math.PI)
                ctx.stroke()
            }

            animationFrameId = window.requestAnimationFrame(render)
        }

        render()
        return () => window.cancelAnimationFrame(animationFrameId)
    }, [isOpen, isListening])

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

    if (!isOpen) return null

    return (
        <AnimatePresence>
            <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 z-[100] bg-black flex flex-col items-center justify-center"
            >
                <canvas ref={canvasRef} className="absolute inset-0" />

                <div className="relative z-10 flex flex-col items-center gap-8">
                    <div className="h-20 flex items-center justify-center">
                        {transcript && (
                            <p className="text-white/80 text-xl font-medium text-center max-w-xl animate-fade-in-up">
                                &quot;{transcript}&quot;
                            </p>
                        )}
                    </div>

                    <div className="flex gap-4">
                        <Button
                            size="icon"
                            className="h-16 w-16 rounded-full bg-white/10 hover:bg-white/20 backdrop-blur-md border border-white/20"
                            onClick={toggleListening}
                        >
                            {isListening ? <Mic className="h-8 w-8 text-sky-400" /> : <MicOff className="h-8 w-8 text-white/50" />}
                        </Button>
                        <Button
                            size="icon"
                            variant="ghost"
                            className="h-16 w-16 rounded-full hover:bg-white/10 text-white/50"
                            onClick={onClose}
                        >
                            <X className="h-8 w-8" />
                        </Button>
                    </div>
                </div>
            </motion.div>
        </AnimatePresence>
    )
}
