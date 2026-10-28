// @vitest-environment happy-dom

import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@/test/hook-harness'
import type { SystemSettings } from '@/lib/api'

const api = vi.hoisted(() => ({
  get: vi.fn(),
  update: vi.fn(),
  getStatus: vi.fn(),
  meta: vi.fn(),
  refresh: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  settingsApi: { get: api.get, update: api.update, getStatus: api.getStatus },
  metaApi: { details: api.meta },
}))
vi.mock('@/contexts/pipeline-capabilities-context', () => ({
  usePipelineCapabilities: () => ({ refresh: api.refresh }),
}))

import { useSettingsPageState } from './use-settings-page-state'

type SettingsPatch = Parameters<typeof import('@/lib/api')['settingsApi']['update']>[0]
let stored: SystemSettings
const hooks: Array<ReturnType<typeof renderHook<ReturnType<typeof useSettingsPageState>>>> = []
const success = { success: true, message: 'ok', updated_keys: [] }

function persist(patch: SettingsPatch) {
  stored = { ...stored, ...structuredClone(patch) }
  return success
}

async function openSettings() {
  const hook = renderHook(useSettingsPageState)
  hooks.push(hook)
  await act(async () => {})
  expect(hook.result.current.loading).toBe(false)
  return hook
}

async function advance(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms) })
}

describe('settings automatic saving', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    stored = {
      feature_flags: { kg_enabled: false },
      governance: { enabled: false, pii_anonymize: false, secrets_redact: false, quarantine_on_drop: false },
      chat: { stream_heartbeat_sec: 10, stream_cancel_on_disconnect: true },
    } as SystemSettings
    api.get.mockImplementation(async () => structuredClone(stored))
    api.update.mockImplementation(async (patch: SettingsPatch) => persist(patch))
    api.getStatus.mockResolvedValue({})
    api.meta.mockResolvedValue({})
    api.refresh.mockResolvedValue(undefined)
  })

  afterEach(async () => {
    for (const hook of hooks.splice(0)) hook.unmount()
    await act(async () => {})
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('saves a switch immediately and reads it back without loading the page again', async () => {
    const hook = await openSettings()
    expect(api.update).not.toHaveBeenCalled()
    await act(async () => { hook.result.current.updateGovernance({ enabled: true }) })
    expect(api.update).toHaveBeenCalledTimes(1)
    expect(stored.governance.enabled).toBe(true)
    expect(api.get).toHaveBeenCalledTimes(2)
    expect(hook.result.current.loading).toBe(false)
    expect(hook.result.current.isGovernanceEnabled).toBe(true)
    expect(hook.result.current.hasChanges).toBe(false)
  })

  it('hydrates and saves a custom OpenAI-compatible embedding model through central settings', async () => {
    stored.embedding = { provider: 'openai_compatible', model: 'custom-embedding-v1', api_base: 'http://localhost:9001/v1', api_key: '' }
    const hook = await openSettings()
    const configured = hook.result.current.groupedProviders.embedding.find(provider => provider.isConfigured)
    expect(configured?.id).toBe('openai-embedding')
    expect(configured?.config).toMatchObject({ model: 'custom-embedding-v1', apiBase: 'http://localhost:9001/v1' })
    await act(async () => { await hook.result.current.handleSaveConfig('openai-embedding', { model: 'custom-embedding-v2', apiBase: 'http://localhost:9001/v1', apiKey: '' }) })
    expect(stored.embedding).toMatchObject({ provider: 'openai_compatible', model: 'custom-embedding-v2' })
    expect(hook.result.current.groupedProviders.embedding.find(provider => provider.isConfigured)?.config?.model).toBe('custom-embedding-v2')
  })

  it('saves the final text value after typing stops', async () => {
    const hook = await openSettings()
    act(() => { hook.result.current.updateMinerU({ api_base: 'https://first.test' }) })
    await advance(300)
    act(() => { hook.result.current.updateMinerU({ api_base: 'https://final.test' }) })
    await advance(499)
    expect(api.update).not.toHaveBeenCalled()
    await advance(1)
    expect(api.update).toHaveBeenCalledTimes(1)
    expect(stored.mineru.api_base).toBe('https://final.test')
    expect(hook.result.current.hasChanges).toBe(false)
  })

  it('serializes saves and preserves edits made during a slow request', async () => {
    const hook = await openSettings()
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    api.update.mockImplementationOnce(async (patch: SettingsPatch) => { await gate; return persist(patch) })
    act(() => { hook.result.current.updateGovernance({ enabled: true }) })
    expect(api.update).toHaveBeenCalledTimes(1)
    act(() => {
      hook.result.current.updateGovernance({ pii_anonymize: true })
      hook.result.current.updateGovernance({ enabled: false })
      hook.result.current.updateChat({ stream_cancel_on_disconnect: false })
    })
    expect(api.update).toHaveBeenCalledTimes(1)
    expect(hook.result.current.isPiiAnonymizeEnabled).toBe(true)
    await act(async () => { release() })
    expect(api.update).toHaveBeenCalledTimes(2)
    expect(stored.governance).toMatchObject({ enabled: false, pii_anonymize: true })
    expect(stored.chat.stream_cancel_on_disconnect).toBe(false)
    expect(hook.result.current.hasChanges).toBe(false)
  })

  it('retains the draft on failure and retries the latest values', async () => {
    const hook = await openSettings()
    api.update.mockRejectedValueOnce(new Error('network unavailable'))
    await act(async () => { hook.result.current.updateGovernance({ enabled: true }) })
    expect(hook.result.current.isGovernanceEnabled).toBe(true)
    expect(hook.result.current.hasChanges).toBe(true)
    expect(hook.result.current.saveError).toContain('network unavailable')
    await advance(6000)
    expect(api.update).toHaveBeenCalledTimes(1)
    expect(hook.result.current.saveError).toContain('network unavailable')
    await act(async () => { await hook.result.current.retrySave() })
    expect(stored.governance.enabled).toBe(true)
    expect(hook.result.current.saveError).toBeNull()
    expect(hook.result.current.hasChanges).toBe(false)
  })

  it('does not acknowledge a rejected save response', async () => {
    const hook = await openSettings()
    api.update.mockResolvedValueOnce({ success: false, message: 'write rejected', updated_keys: [] })
    await act(async () => { hook.result.current.updateGovernance({ enabled: true }) })
    expect(hook.result.current.hasChanges).toBe(true)
    expect(hook.result.current.saveError).toContain('write rejected')
    expect(stored.governance.enabled).toBe(false)
  })

  it('flushes a pending text edit when leaving the page', async () => {
    const hook = await openSettings()
    act(() => { hook.result.current.updateChat({ stream_heartbeat_sec: 12 }) })
    expect(api.update).not.toHaveBeenCalled()
    hook.unmount()
    hooks.splice(hooks.indexOf(hook), 1)
    await act(async () => {})
    expect(stored.chat.stream_heartbeat_sec).toBe(12)
    const reopened = await openSettings()
    expect(reopened.result.current.chatMerged.stream_heartbeat_sec).toBe(12)
  })

  it('preserves a newer switch value while the previous save is being read back', async () => {
    const hook = await openSettings()
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    api.get.mockImplementationOnce(async () => {
      const snapshot = structuredClone(stored)
      await gate
      return snapshot
    })
    await act(async () => { hook.result.current.updateGovernance({ enabled: true }) })
    act(() => { hook.result.current.updateGovernance({ enabled: false }) })
    expect(hook.result.current.isGovernanceEnabled).toBe(false)
    expect(api.update).toHaveBeenCalledTimes(1)
    await act(async () => { release() })
    expect(stored.governance.enabled).toBe(false)
    expect(hook.result.current.isGovernanceEnabled).toBe(false)
    expect(api.update).toHaveBeenCalledTimes(2)
    expect(hook.result.current.hasChanges).toBe(false)
  })

  it('keeps the typing pause when an earlier switch save finishes', async () => {
    const hook = await openSettings()
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    api.update.mockImplementationOnce(async (patch: SettingsPatch) => { await gate; return persist(patch) })
    act(() => { hook.result.current.updateGovernance({ enabled: true }) })
    act(() => { hook.result.current.updateChat({ stream_heartbeat_sec: 16 }) })
    await advance(200)
    await act(async () => { release() })
    expect(api.update).toHaveBeenCalledTimes(1)
    expect(hook.result.current.chatMerged.stream_heartbeat_sec).toBe(16)
    await advance(299)
    expect(api.update).toHaveBeenCalledTimes(1)
    await advance(1)
    expect(stored.chat.stream_heartbeat_sec).toBe(16)
    expect(api.update).toHaveBeenCalledTimes(2)
    expect(hook.result.current.hasChanges).toBe(false)
  })

  it('retains edits when the save succeeds but confirmation fails', async () => {
    const hook = await openSettings()
    api.get.mockRejectedValueOnce(new Error('confirmation unavailable'))
    await act(async () => { hook.result.current.updateGovernance({ enabled: true }) })
    expect(stored.governance.enabled).toBe(true)
    expect(hook.result.current.isGovernanceEnabled).toBe(true)
    expect(hook.result.current.hasChanges).toBe(true)
    expect(hook.result.current.saveError).toContain('confirmation unavailable')
    expect(hook.result.current.loading).toBe(false)
    await advance(6000)
    expect(api.update).toHaveBeenCalledTimes(1)
    await act(async () => { await hook.result.current.retrySave() })
    expect(hook.result.current.hasChanges).toBe(false)
    expect(hook.result.current.saveError).toBeNull()
  })

  it('drains edits made during an active save after leaving the page', async () => {
    const hook = await openSettings()
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    api.update.mockImplementationOnce(async (patch: SettingsPatch) => { await gate; return persist(patch) })
    act(() => { hook.result.current.updateGovernance({ enabled: true }) })
    act(() => { hook.result.current.updateChat({ stream_heartbeat_sec: 18 }) })
    hook.unmount()
    hooks.splice(hooks.indexOf(hook), 1)
    expect(api.update).toHaveBeenCalledTimes(1)
    await act(async () => { release() })
    expect(stored.governance.enabled).toBe(true)
    expect(stored.chat.stream_heartbeat_sec).toBe(18)
    expect(api.update).toHaveBeenCalledTimes(2)
    const reopened = await openSettings()
    expect(reopened.result.current.chatMerged.stream_heartbeat_sec).toBe(18)
  })

  it('uses the latest feature value when toggled twice before a save completes', async () => {
    const hook = await openSettings()
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    api.update.mockImplementationOnce(async (patch: SettingsPatch) => { await gate; return persist(patch) })
    act(() => {
      hook.result.current.toggleFeature('kg_enabled')
      hook.result.current.toggleFeature('kg_enabled')
    })
    expect(hook.result.current.getFeatureValue('kg_enabled')).toBe(false)
    await act(async () => { release() })
    expect(stored.feature_flags.kg_enabled).toBe(false)
    expect(hook.result.current.hasChanges).toBe(false)
  })
})
