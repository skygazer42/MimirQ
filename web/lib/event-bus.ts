type AppEventMap = {
  'chat:send': string
  'chat:focus-message': { messageId: string; documentId?: string | null; chunkId?: string | null }
  'command-menu:set-open': { open: boolean }
  'command-menu:toggle': undefined
}

type EventHandler<EventMap extends Record<string, unknown>, K extends keyof EventMap> = (payload: EventMap[K]) => void

class EventBus<EventMap extends Record<string, unknown>> {
  private handlers = new Map<keyof EventMap, Set<unknown>>()

  on<K extends keyof EventMap>(event: K, handler: EventHandler<EventMap, K>) {
    const listeners = this.handlers.get(event) ?? new Set<unknown>()
    listeners.add(handler)
    this.handlers.set(event, listeners)
    return () => this.off(event, handler)
  }

  off<K extends keyof EventMap>(event: K, handler: EventHandler<EventMap, K>) {
    const listeners = this.handlers.get(event)
    if (!listeners) return
    listeners.delete(handler)
    if (listeners.size === 0) {
      this.handlers.delete(event)
    }
  }

  emit<K extends keyof EventMap>(event: K, payload: EventMap[K]) {
    const listeners = this.handlers.get(event)
    if (!listeners) return
    listeners.forEach((handler) => {
      ;(handler as EventHandler<EventMap, K>)(payload)
    })
  }
}

export const globalEventBus = new EventBus<AppEventMap>()
