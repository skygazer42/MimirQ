// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ConnectorRunOut } from '@/types/connectors'

vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))

import { KnowledgeConnectorRunsPanel } from './knowledge-connector-runs-panel'

const actions = {
  onCancelConnectorRun: vi.fn(),
  onResumeConnectorRun: vi.fn(),
  onRetryFailedConnectorRun: vi.fn(),
  onLoadConnectorRuns: vi.fn(),
}

describe('connector task result feedback', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    vi.clearAllMocks()
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('shows the request error instead of an empty success and keeps refresh available', () => {
    act(() =>
      root.render(
        <KnowledgeConnectorRunsPanel
          {...actions}
          selectedDatasetId="dataset-a"
          connectorRuns={[]}
          connectorRunsLoading={false}
          connectorRunsError="导入任务服务不可用"
        />,
      ),
    )

    expect(container.querySelector('[role="alert"]')?.textContent).toContain('导入任务服务不可用')
    expect(container.textContent).not.toContain('connectorRuns.empty.title')
    const refreshButton = container.querySelector<HTMLButtonElement>('button[aria-label="刷新"]')
    expect(refreshButton).not.toBeNull()
    act(() => refreshButton?.click())
    expect(actions.onLoadConnectorRuns).toHaveBeenCalledWith({ datasetId: 'dataset-a' })
  })

  it('keeps a real zero progress value ahead of legacy counters', () => {
    const run: ConnectorRunOut = {
      id: 'run-a',
      tenant_id: 'tenant-a',
      connector_id: 'url_batch',
      status: 'running',
      created_at: '2026-11-05T00:00:00Z',
      stats: { total_items: 0, items_total: 100, processed_items: 0, items_processed: 100 },
    }
    act(() =>
      root.render(
        <KnowledgeConnectorRunsPanel
          {...actions}
          connectorRuns={[run]}
          connectorRunsLoading={false}
          connectorRunsError={null}
        />,
      ),
    )

    expect(container.textContent).not.toContain('100% Complete')
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })

  it('keeps the cached tasks visible when a refresh fails', () => {
    const run: ConnectorRunOut = {
      id: 'cached-run',
      tenant_id: 'tenant-a',
      connector_id: 'url_batch',
      status: 'running',
      created_at: '2026-11-05T00:00:00Z',
    }
    act(() =>
      root.render(
        <KnowledgeConnectorRunsPanel
          {...actions}
          connectorRuns={[run]}
          connectorRunsLoading={false}
          connectorRunsError="刷新失败"
        />,
      ),
    )
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('刷新失败')
    expect(container.textContent).toContain('url_batch')
  })

  it.each(['confluence_space', 'jira_project', 'github_repo', 'drive_files'])(
    'keeps %s history readable without unsupported retry or resume actions',
    (connectorId) => {
      const run: ConnectorRunOut = {
        id: 'failed-run',
        tenant_id: 'tenant-a',
        connector_id: connectorId,
        status: 'failed',
        supports_retry_failed: false,
        supports_resume: false,
        created_at: '2026-11-05T00:00:00Z',
      }
      act(() =>
        root.render(
          <KnowledgeConnectorRunsPanel
            {...actions}
            connectorRuns={[run, { ...run, id: 'cancelled-run', status: 'cancelled' }]}
            connectorRunsLoading={false}
            connectorRunsError={null}
          />,
        ),
      )

      expect(container.textContent).toContain(connectorId)
      expect(container.querySelectorAll('button[aria-label="复制"]')).toHaveLength(2)
      expect(container.querySelector('button[aria-label="重试"]')).toBeNull()
      expect(container.querySelector('button[aria-label="继续"]')).toBeNull()
      expect(actions.onRetryFailedConnectorRun).not.toHaveBeenCalled()
      expect(actions.onResumeConnectorRun).not.toHaveBeenCalled()
    },
  )

  it.each([
    ['url_batch', 'failed', '重试', 'onRetryFailedConnectorRun'],
    ['web_crawl', 'failed', '重试', 'onRetryFailedConnectorRun'],
    ['url_batch', 'cancelled', '继续', 'onResumeConnectorRun'],
    ['web_crawl', 'cancelled', '继续', 'onResumeConnectorRun'],
  ] as const)('runs the supported %s %s action', (connectorId, status, label, action) => {
    const run: ConnectorRunOut = {
      id: 'supported-run',
      tenant_id: 'tenant-a',
      connector_id: connectorId,
      status,
      supports_retry_failed: true,
      supports_resume: true,
      stats: { failed_urls: ['https://example.com/failed.md'] },
      created_at: '2026-11-05T00:00:00Z',
    }
    act(() =>
      root.render(
        <KnowledgeConnectorRunsPanel
          {...actions}
          connectorRuns={[run]}
          connectorRunsLoading={false}
          connectorRunsError={null}
        />,
      ),
    )

    const buttons = container.querySelectorAll<HTMLButtonElement>(`button[aria-label="${label}"]`)
    expect(buttons).toHaveLength(1)
    act(() => buttons[0].click())
    expect(actions[action]).toHaveBeenCalledOnce()
    expect(actions[action]).toHaveBeenCalledWith('supported-run')
  })

  it.each(['failed', 'cancelled'] as const)('does not infer %s actions from a cached connector ID', (status) => {
    const run: ConnectorRunOut = {
      id: 'cached-run',
      tenant_id: 'tenant-a',
      connector_id: 'url_batch',
      status,
      created_at: '2026-11-05T00:00:00Z',
    }
    act(() =>
      root.render(
        <KnowledgeConnectorRunsPanel
          {...actions}
          connectorRuns={[run]}
          connectorRunsLoading={false}
          connectorRunsError={null}
        />,
      ),
    )

    expect(container.querySelector('button[aria-label="重试"]')).toBeNull()
    expect(container.querySelector('button[aria-label="继续"]')).toBeNull()
    expect(container.querySelector('button[aria-label="复制"]')).not.toBeNull()
  })

  it('does not offer retry when the backend reports no retryable URLs', () => {
    const run: ConnectorRunOut = {
      id: 'no-retryable-urls',
      tenant_id: 'tenant-a',
      connector_id: 'url_batch',
      status: 'failed',
      supports_retry_failed: false,
      supports_resume: true,
      stats: { failed_urls: [] },
      created_at: '2026-11-05T00:00:00Z',
    }
    act(() =>
      root.render(
        <KnowledgeConnectorRunsPanel
          {...actions}
          connectorRuns={[run]}
          connectorRunsLoading={false}
          connectorRunsError={null}
        />,
      ),
    )

    expect(container.querySelector('button[aria-label="重试"]')).toBeNull()
    expect(container.querySelector('button[aria-label="继续"]')).toBeNull()
  })

  it.each(['running', 'completed'] as const)('does not show retry or resume actions for a %s task', (status) => {
    const run: ConnectorRunOut = {
      id: 'current-run',
      tenant_id: 'tenant-a',
      connector_id: 'url_batch',
      status,
      supports_retry_failed: true,
      supports_resume: true,
      stats: { failed_urls: ['https://example.com/failed.md'] },
      created_at: '2026-11-05T00:00:00Z',
    }
    act(() =>
      root.render(
        <KnowledgeConnectorRunsPanel
          {...actions}
          connectorRuns={[run]}
          connectorRunsLoading={false}
          connectorRunsError={null}
        />,
      ),
    )

    expect(container.querySelector('button[aria-label="重试"]')).toBeNull()
    expect(container.querySelector('button[aria-label="继续"]')).toBeNull()
    expect(container.querySelector('button[aria-label="复制"]')).not.toBeNull()
    const cancelButton = container.querySelector<HTMLButtonElement>('button[aria-label="取消"]')
    if (status === 'running') {
      expect(cancelButton).not.toBeNull()
      act(() => cancelButton?.click())
      expect(actions.onCancelConnectorRun).toHaveBeenCalledWith('current-run')
    } else {
      expect(cancelButton).toBeNull()
    }
  })
})
