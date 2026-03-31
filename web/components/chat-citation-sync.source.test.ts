import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chat citation sync source', () => {
  it('wires viewer-to-chat return jumps through persisted citation source context', () => {
    const messageSrc = fs.readFileSync(path.resolve(__dirname, 'chat/message-item.tsx'), 'utf8')
    const chatAreaSrc = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')
    const headerSrc = fs.readFileSync(path.resolve(__dirname, 'document-viewer/document-viewer-header.tsx'), 'utf8')
    const viewerStateSrc = fs.readFileSync(path.resolve(__dirname, 'document-viewer/use-document-viewer-panel-state.ts'), 'utf8')
    const storeSrc = fs.readFileSync(path.resolve(__dirname, '..', 'store', 'document-view.ts'), 'utf8')
    const eventBusSrc = fs.readFileSync(path.resolve(__dirname, '..', 'lib', 'event-bus.ts'), 'utf8')

    expect(eventBusSrc).toContain("'chat:focus-message'")
    expect(storeSrc).toContain('sourceContext')
    expect(storeSrc).toContain("kind: 'chat-citation'")
    expect(messageSrc).toContain('sourceContext:')
    expect(messageSrc).toContain("kind: 'chat-citation'")
    expect(chatAreaSrc).toContain("globalEventBus.on('chat:focus-message'")
    expect(chatAreaSrc).toContain('data-chat-message-id={message.id}')
    expect(headerSrc).toContain('onJumpToSource')
    expect(headerSrc).toContain('回到对话引用')
    expect(viewerStateSrc).toContain("globalEventBus.emit('chat:focus-message'")
  })
})
