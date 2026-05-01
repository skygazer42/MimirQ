import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history page message bubbles', () => {
  it('renders history messages through the minimal chat variant while keeping explicit bubble surfaces for both roles', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')
    const messageSrc = fs.readFileSync(path.resolve(__dirname, '../../components/chat/message-item.tsx'), 'utf8')

    expect(pageSrc).toContain('<ChatMessageItem message={message} variant="minimal" />')
    expect(messageSrc).toContain("variant === 'minimal'")
    expect(messageSrc).toContain("rounded-2xl rounded-br-md border border-[#BDE0FE] bg-[#A2D2FF] text-black")
    expect(messageSrc).toContain("max-w-none break-words leading-relaxed text-primary-foreground [&>*]:text-inherit")
    expect(messageSrc).toContain('whitespace-pre-wrap font-normal text-primary-foreground [&>*]:text-inherit')
    expect(messageSrc).toContain("rounded-2xl rounded-bl-md border border-border/60 bg-background/92")
  })
})
