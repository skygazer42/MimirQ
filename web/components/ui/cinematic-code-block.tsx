'use client'

import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

type CinematicCodeBlockProps = Readonly<{
  language: string
  code: string
}>

export function CinematicCodeBlock({ language, code }: CinematicCodeBlockProps) {
  return (
    <div className="relative group rounded-lg overflow-hidden my-4 border border-border/50 shadow-sm motion-safe:animate-fade-in-up">
      <div className="flex items-center px-4 py-2 bg-secondary/30 border-b border-border/60">
        <div className="flex gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-destructive/80" />
          <div className="w-2.5 h-2.5 rounded-full bg-warning/80" />
          <div className="w-2.5 h-2.5 rounded-full bg-success/80" />
        </div>
        <span className="ml-4 text-[11px] font-mono text-muted-foreground uppercase">{language}</span>
      </div>
      <SyntaxHighlighter
        style={oneDark}
        language={language}
        PreTag="div"
        customStyle={{
          margin: 0,
          borderRadius: 0,
          background: 'transparent',
          fontSize: '0.85em',
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  )
}
