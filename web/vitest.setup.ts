import { randomUUID } from 'node:crypto'
import { BroadcastChannel as NodeBroadcastChannel } from 'node:worker_threads'
import { afterAll } from 'vitest'

const NativeBroadcastChannel = globalThis.BroadcastChannel

if (typeof window !== 'undefined' && Object.is(NativeBroadcastChannel, NodeBroadcastChannel)) {
  // happy-dom falls back to Node's registry, which is shared across Vitest workers.
  const namespace = randomUUID()
  const channels = new Set<BroadcastChannel>()

  class FileBroadcastChannel extends NativeBroadcastChannel {
    constructor(name: string) {
      super(`${namespace}:${name}`)
      Object.defineProperty(this, 'name', { configurable: true, value: name })
      channels.add(this)
    }

    override close() {
      channels.delete(this)
      super.close()
    }
  }

  globalThis.BroadcastChannel = FileBroadcastChannel
  afterAll(() => {
    for (const channel of channels) channel.close()
    globalThis.BroadcastChannel = NativeBroadcastChannel
  })
}
