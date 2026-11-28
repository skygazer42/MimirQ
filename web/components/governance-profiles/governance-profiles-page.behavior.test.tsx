// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { waitForAssertion } from '@/test/hook-harness'
import type { GovernanceProfileOut } from '@/types'

const api = vi.hoisted(() => ({
  listGovernanceProfiles: vi.fn(),
  getGovernanceProfileResolved: vi.fn(),
  updateGovernanceProfile: vi.fn(),
}))
vi.mock('@/lib/api/pipeline', () => ({ pipelineApi: api }))
vi.mock('@/lib/api', () => ({ pipelineApi: api }))
vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))
vi.mock('@/i18n/navigation', () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a>,
}))
vi.mock('./profile-editor-drawer', () => ({ ProfileEditorDrawer: () => null }))
vi.mock('./cleaning-preview', () => ({ CleaningPreview: () => null }))

import { GovernanceProfilesPage } from './governance-profiles-page'

const builtin: GovernanceProfileOut = {
  key: 'builtin:pdf_text',
  name: 'PDF 文本版',
  is_system: true,
  payload: {
    version: '1',
    input_formats: ['markdown'],
    pipeline_patch: { governance_enabled: true, governance_remove_toc_lines: true },
    regex_rules: [],
  },
}
const custom: GovernanceProfileOut = {
  id: 'team-profile',
  key: 'team:clean',
  name: '团队模板',
  is_system: false,
  payload: {
    ...builtin.payload,
    extends: builtin.key,
    pipeline_patch: {
      governance_remove_noise_lines: false,
      governance_max_blank_lines: 0,
      governance_pii_anonymize: true,
    },
  },
}
const cleanup: Array<() => void> = []
beforeEach(() => vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true))
afterEach(() => {
  cleanup.splice(0).forEach((dispose) => dispose())
  vi.resetAllMocks()
  vi.unstubAllGlobals()
})

it('shows all sources without losing selection and distinguishes inherited, disabled, unset and explicit values', async () => {
  api.listGovernanceProfiles.mockResolvedValue({ total: 2, items: [builtin, custom] })
  api.getGovernanceProfileResolved.mockImplementation(async (ref: string) => {
    const profile = ref === builtin.key ? builtin : custom
    return {
      profile,
      chain: profile.is_system ? [builtin] : [builtin, custom],
      effective: {
        ...profile.payload,
        pipeline_patch: {
          ...builtin.payload.pipeline_patch,
          ...profile.payload.pipeline_patch,
          governance_pii_mask: null,
        },
      },
    }
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  cleanup.push(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
  })
  await act(async () =>
    root.render(
      <QueryClientProvider client={client}>
        <GovernanceProfilesPage />
      </QueryClientProvider>,
    ),
  )
  const rows = () => container.querySelectorAll('[data-profile-ref]')
  await waitForAssertion(() => expect(rows()).toHaveLength(1))
  const all = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.startsWith('全部'))!
  await act(async () => all.click())
  await waitForAssertion(() => expect(rows()).toHaveLength(2))
  expect(container.querySelector('[aria-current="true"]')?.getAttribute('data-profile-ref')).toBe(builtin.key)
  await act(async () => container.querySelector<HTMLButtonElement>('[data-profile-ref="team-profile"]')!.click())
  await waitForAssertion(() =>
    expect(container.querySelector('[data-profile-detail] h2')?.textContent).toBe(custom.name),
  )
  const rule = (label: string) =>
    Array.from(container.querySelectorAll('[data-rule-state]')).find((row) => row.textContent?.includes(label))!
  await waitForAssertion(() => expect(rule('移除目录行')).toBeDefined())
  expect(rule('移除目录行').getAttribute('data-rule-state')).toBe('inherited')
  expect(rule('移除目录行').textContent).toContain('继承')
  expect(rule('清理噪声行').getAttribute('data-rule-state')).toBe('disabled')
  expect(rule('清理噪声行').textContent).toContain('关闭')
  expect(rule('连续空行上限').getAttribute('data-rule-state')).toBe('resolved')
  expect(rule('连续空行上限').textContent).toContain('0')
  expect(rule('个人信息替换文本').getAttribute('data-rule-state')).toBe('unset')
  expect(rule('个人信息替换文本').textContent).toContain('沿用默认')
  expect(container.querySelector('[data-profile-detail]')?.textContent).toContain('个人信息脱敏')
  const previewBtn = Array.from(container.querySelectorAll('[data-profile-detail] button')).find((button) =>
    button.textContent?.includes('清洗预览'),
  )
  expect(previewBtn).toBeDefined()
  expect(container.querySelector('[data-profile-detail] details')).toBeNull()
  const noiseSwitch = container.querySelector<HTMLButtonElement>('[aria-label="切换清理噪声行"]')!
  expect(noiseSwitch).not.toBeNull()
  expect(noiseSwitch.getAttribute('aria-checked')).toBe('false')
  api.updateGovernanceProfile.mockResolvedValueOnce({
    ...custom,
    payload: {
      ...custom.payload,
      pipeline_patch: { ...custom.payload.pipeline_patch, governance_remove_noise_lines: true },
    },
  })
  await act(async () => noiseSwitch.click())
  await waitForAssertion(() =>
    expect(api.updateGovernanceProfile).toHaveBeenCalledWith(
      'team-profile',
      expect.objectContaining({
        payload: expect.objectContaining({
          pipeline_patch: expect.objectContaining({ governance_remove_noise_lines: true }),
        }),
      }),
    ),
  )
})
