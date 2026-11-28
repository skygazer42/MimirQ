type AppEventMap = {
  'chat:send': string
  'chat:submit': string
  'chat:focus-message': { messageId: string; documentId?: string | null; chunkId?: string | null }
}

type EventHandler<K extends keyof AppEventMap> = (payload: AppEventMap[K]) => void

class EventBus {
  private readonly handlers: { [K in keyof AppEventMap]: Set<EventHandler<K>> } = {
    'chat:send': new Set(),
    'chat:submit': new Set(),
    'chat:focus-message': new Set(),
  }

  on<K extends keyof AppEventMap>(event: K, handler: EventHandler<K>) {
    const listeners = this.handlers[event]
    listeners.add(handler)
    return () => {
      listeners.delete(handler)
    }
  }

  emit<K extends keyof AppEventMap>(event: K, payload: AppEventMap[K]): number {
    let delivered = 0
    for (const handler of this.handlers[event]) {
      handler(payload)
      delivered += 1
    }
    return delivered
  }
}

export const globalEventBus = new EventBus()
