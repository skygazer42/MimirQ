type EventHandler = (payload: any) => void

class EventBus {
  private handlers: Record<string, EventHandler[]> = {}

  on(event: string, handler: EventHandler) {
    if (!this.handlers[event]) {
      this.handlers[event] = []
    }
    this.handlers[event].push(handler)
    return () => this.off(event, handler)
  }

  off(event: string, handler: EventHandler) {
    if (!this.handlers[event]) return
    this.handlers[event] = this.handlers[event].filter(h => h !== handler)
  }

  emit(event: string, payload: any) {
    if (!this.handlers[event]) return
    this.handlers[event].forEach(h => h(payload))
  }
}

export const globalEventBus = new EventBus()
