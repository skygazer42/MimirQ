"use client"

import { useEffect, useState, useRef, useMemo } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

// 调整打字速度配置 (ms)
const MIN_TYPE_SPEED = 5
const MAX_TYPE_SPEED = 15
const PUNCTUATION_DELAY = 150 // 遇到标点符号时的额外停顿

interface CinematicTypewriterProps {
  content: string
  onComplete?: () => void
  isStreaming?: boolean
  className?: string
}

export function CinematicTypewriter({
  content,
  onComplete,
  isStreaming = false,
  className,
}: CinematicTypewriterProps) {
  const [displayedContent, setDisplayedContent] = useState("")
  const [isTyping, setIsTyping] = useState(false)
  const indexRef = useRef(0)
  const timeoutRef = useRef<NodeJS.Timeout | null>(null)

  // Markdown 组件配置
  const markdownComponents = useMemo(() => ({
    p: ({ children }: { children?: React.ReactNode }) => <p className="mb-3 last:mb-0 leading-relaxed animate-fade-in">{children}</p>,
    ul: ({ children }: { children?: React.ReactNode }) => (
        <ul className="list-disc pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60 animate-fade-in">{children}</ul>
    ),
    ol: ({ children }: { children?: React.ReactNode }) => (
        <ol className="list-decimal pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60 animate-fade-in">{children}</ol>
    ),
    code: ({ className, children, ...props }: any) => {
        const match = /language-(\w+)/.exec(className || '')
        return match ? (
            <div className="relative group rounded-lg overflow-hidden my-4 border border-border/50 shadow-sm animate-fade-in-up">
                {/* Mac 风格窗口头 */}
                <div className="flex items-center px-4 py-2 bg-slate-950/50 border-b border-white/10">
                    <div className="flex gap-1.5">
                        <div className="w-2.5 h-2.5 rounded-full bg-red-500/80" />
                        <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/80" />
                        <div className="w-2.5 h-2.5 rounded-full bg-green-500/80" />
                    </div>
                    <span className="ml-4 text-[10px] font-mono text-slate-400 uppercase">{match[1]}</span>
                </div>
                <SyntaxHighlighter
                    {...props}
                    style={oneDark}
                    language={match[1]}
                    PreTag="div"
                    customStyle={{
                        margin: 0,
                        borderRadius: 0,
                        background: 'rgba(2, 6, 23, 0.5)', // slate-950/50
                        fontSize: '0.85em',
                    }}
                >
                    {String(children).replace(/\n$/, '')}
                </SyntaxHighlighter>
            </div>
        ) : (
            <code className="bg-secondary/50 px-1.5 py-0.5 rounded-md text-sm font-mono text-primary" {...props}>
                {children}
            </code>
        )
    },
  }), [])

  useEffect(() => {
    // 如果已经不再 streaming 且显示内容已追上，直接完成
    if (!isStreaming && indexRef.current >= content.length) {
        if (displayedContent !== content) {
            setDisplayedContent(content)
        }
        setIsTyping(false)
        onComplete?.()
        return
    }

    setIsTyping(true)

    const typeNextChar = () => {
      if (indexRef.current >= content.length) {
        if (!isStreaming) {
            setIsTyping(false)
            onComplete?.()
        } else {
            // Wait for more content from stream
            timeoutRef.current = setTimeout(typeNextChar, 50) 
        }
        return
      }

      const char = content[indexRef.current]
      indexRef.current++
      setDisplayedContent((prev) => prev + char)

      let delay = Math.random() * (MAX_TYPE_SPEED - MIN_TYPE_SPEED) + MIN_TYPE_SPEED
      
      // 模拟思考停顿
      if (['.', '!', '?', '。', '！', '？'].includes(char)) {
        delay += PUNCTUATION_DELAY
      } else if (char === '\n') {
        delay += 20
      }

      timeoutRef.current = setTimeout(typeNextChar, delay)
    }

    // 只有当有新内容未显示时才启动打字循环，避免重复重置
    if (timeoutRef.current === null && indexRef.current < content.length) {
        typeNextChar()
    }

    return () => {
        // Cleanup is tricky with self-scheduling loop, usually handled by ref check
    }
  }, [content, isStreaming, onComplete])

  // 组件卸载时清理
  useEffect(() => {
      return () => {
          if (timeoutRef.current) clearTimeout(timeoutRef.current)
      }
  }, [])

  return (
    <div className={cn("relative leading-relaxed", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={markdownComponents}
      >
        {displayedContent}
      </ReactMarkdown>
      
      {/* 电影感光标 */}
      {isTyping && (
        <span className="inline-block w-1.5 h-5 ml-0.5 align-middle bg-primary animate-blink shadow-[0_0_8px_rgba(var(--primary),0.8)] rounded-full" />
      )}
    </div>
  )
}
