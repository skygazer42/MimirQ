'use client'

import { motion, useReducedMotion } from 'framer-motion'
import { useLayoutEffect, useRef, useState } from 'react'

import { X, Mic, MicOff } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type VoiceModeOverlayProps = {
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
  onend: (() => void) | null
  onerror: (() => void) | null
  start: () => void
  stop: () => void
}

type WindowWithSpeechRecognition = Window & {
  webkitSpeechRecognition?: new () => SpeechRecognitionLike
}

type RecognitionStatus = 'checking' | 'unavailable' | 'ready' | 'listening' | 'stopping'

export function VoiceModeOverlay({ isOpen, onClose, onSend }: Readonly<VoiceModeOverlayProps>) {
  const [recognitionStatus, setRecognitionStatus] = useState<RecognitionStatus>('checking')
  const [recognitionError, setRecognitionError] = useState<string | null>(null)
  const [transcript, setTranscript] = useState('')
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const transcriptRef = useRef('')
  const sendRequestedRef = useRef(false)
  const onSendRef = useRef(onSend)
  const reduceMotion = useReducedMotion()
  const isStopping = recognitionStatus === 'stopping'
  const isListening = recognitionStatus === 'listening' || isStopping
  const canToggle = recognitionStatus === 'ready' || recognitionStatus === 'listening'

  useLayoutEffect(() => {
    onSendRef.current = onSend
  }, [onSend])

  useLayoutEffect(() => {
    if (!isOpen) return

    setTranscript('')
    setRecognitionError(null)
    const { webkitSpeechRecognition: SpeechRecognition } = globalThis.window as WindowWithSpeechRecognition
    if (SpeechRecognition === undefined) {
      setRecognitionStatus('unavailable')
      return
    }

    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'zh-CN'

    recognition.onresult = (event) => {
      if (recognitionRef.current !== recognition) return
      let finalTranscript = ''
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index]
        if (result.isFinal) {
          finalTranscript += result[0].transcript
        }
      }
      transcriptRef.current = finalTranscript
      setTranscript(finalTranscript)
    }

    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return
      setRecognitionStatus('ready')
      const shouldSend = sendRequestedRef.current
      sendRequestedRef.current = false
      const text = transcriptRef.current.trim()
      if (shouldSend && text) onSendRef.current(text)
    }
    recognition.onerror = () => {
      if (recognitionRef.current !== recognition) return
      sendRequestedRef.current = false
      setRecognitionStatus('ready')
      setRecognitionError('语音输入失败，请重试')
    }
    recognitionRef.current = recognition
    setRecognitionStatus('ready')
    return () => {
      recognitionRef.current = null
      sendRequestedRef.current = false
      recognition.onresult = null
      recognition.onend = null
      recognition.onerror = null
      recognition.stop()
    }
  }, [isOpen])

  function handleMicrophoneClick() {
    const recognition = recognitionRef.current
    if (recognition === null || !canToggle) return

    if (isListening) {
      sendRequestedRef.current = true
      setRecognitionStatus('stopping')
      recognition.stop()
      return
    }

    transcriptRef.current = ''
    setTranscript('')
    setRecognitionError(null)
    try {
      recognition.start()
      setRecognitionStatus('listening')
    } catch {
      setRecognitionError('无法启动语音输入，请重试')
    }
  }

  function closeVoiceMode() {
    sendRequestedRef.current = false
    onClose()
  }

  if (!isOpen) {
    return null
  }

  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      className="fixed inset-0 z-100 flex flex-col items-center justify-center bg-background text-foreground"
    >
      <div className="pointer-events-none absolute inset-0 grid place-items-center" aria-hidden="true">
        <div
          className={cn(
            'col-start-1 row-start-1 size-[204px] rounded-full border-4',
            isListening ? 'border-primary motion-safe:animate-pulse' : 'border-foreground/75',
          )}
        />
        {isListening && (
          <div className="col-start-1 row-start-1 size-[264px] rounded-full border-4 border-primary/30" />
        )}
      </div>

      <div className="relative z-10 flex w-full max-w-xl flex-col items-center gap-8 px-6">
        <div className="flex h-20 w-full overflow-y-auto">
          {transcript && (
            <p className="m-auto w-full text-center text-xl font-medium text-foreground/80 [overflow-wrap:anywhere] motion-safe:animate-fade-in-up">
              &quot;{transcript}&quot;
            </p>
          )}
        </div>

        {recognitionStatus === 'unavailable' ? <p role="status">当前浏览器不支持语音输入</p> : null}
        {recognitionError ? <p role="alert">{recognitionError}</p> : null}

        <div className="flex gap-4">
          <Button
            size="icon"
            className="h-16 w-16 rounded-full glass hover:bg-accent/30 hover:border-primary/30 transition-colors duration-200 motion-reduce:transition-none"
            onClick={handleMicrophoneClick}
            disabled={!canToggle}
            aria-busy={isStopping}
            aria-label={isListening ? '停止语音输入' : '开始语音输入'}
          >
            {isListening ? (
              <Mic className="h-8 w-8 text-primary" />
            ) : (
              <MicOff className="h-8 w-8 text-muted-foreground" />
            )}
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-16 w-16 rounded-full hover:bg-accent/40 text-muted-foreground hover:text-foreground transition-colors duration-200 motion-reduce:transition-none"
            onClick={closeVoiceMode}
            aria-label="关闭语音模式"
          >
            <X className="h-8 w-8" />
          </Button>
        </div>
      </div>
    </motion.div>
  )
}
