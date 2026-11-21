import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'
import {
  createAuditFilterDraft,
  createAuditPurgeParameters,
  formatAuditError,
  getAuditActionLabel,
  getAuditActionTone,
  getAuditFilterError,
  getAuditQueryFilters,
  getAuditResourceLabel,
  parseAuditLocation,
} from './audit-model'

describe('audit filters and operation scopes', () => {
  it('keeps exact identifier filters and restores supported page sizes', () => {
    const scope = parseAuditLocation('?actor_id=acct-a&request_id=req%2Fa%2Bb&page=3&page_size=50&unrelated=x')
    expect(scope).toMatchObject({ page: 3, limit: 50, filters: { actor_id: 'acct-a', request_id: 'req/a+b' } })
    expect(parseAuditLocation('?page=Infinity&page_size=999')).toMatchObject({ page: 1, limit: 20 })
    expect(getAuditQueryFilters({ ...createAuditFilterDraft(), actor_id: '  acct-a  ', request_id: '  ' })).toEqual({
      actor_id: 'acct-a',
    })
  })

  it('rejects a reversed or invalid time range before it becomes an API or purge scope', () => {
    expect(
      getAuditFilterError({
        ...createAuditFilterDraft(),
        since: '2026-10-25T12:00:00Z',
        until: '2026-10-24T12:00:00Z',
      }),
    ).toContain('开始时间')
    expect(getAuditFilterError({ ...createAuditFilterDraft(), since: 'not-a-date' })).toContain('时间')
    expect(getAuditFilterError({ ...createAuditFilterDraft(), request_id: 'r'.repeat(129) })).toContain('请求 ID')
  })

  it('does not silently apply list filters to retention cleanup', () => {
    const params = createAuditPurgeParameters(
      { ...createAuditFilterDraft(), actor_id: 'acct-a', action: 'dataset.update' },
      'retention',
      '90',
      '1000',
      true,
    )
    expect(params).toEqual({ purge_scope: 'retention', retention_days: 90, max_delete: 1000, dry_run: true })
    expect(params).not.toHaveProperty('actor_id')
  })

  it('requires a real exact filter for filtered cleanup and snapshots it', () => {
    expect(() => createAuditPurgeParameters(createAuditFilterDraft(), 'filtered', '90', '1000', true)).toThrow('筛选')
    const filters = { ...createAuditFilterDraft(), request_id: ' req-001 ' }
    const params = createAuditPurgeParameters(filters, 'filtered', '90', '1000', false)
    filters.request_id = 'req-changed'
    expect(params).toMatchObject({ purge_scope: 'filtered', request_id: 'req-001', dry_run: false })
  })

  it('validates cleanup integers using the existing API bounds', () => {
    for (const days of ['', '0', '1.5', '3651'])
      expect(() => createAuditPurgeParameters(createAuditFilterDraft(), 'retention', days, '1000', true)).toThrow(
        '保留天数',
      )
    for (const max of ['', '0', '1000001', '2.5'])
      expect(() => createAuditPurgeParameters(createAuditFilterDraft(), 'retention', '90', max, true)).toThrow(
        '最多清理',
      )
  })

  it('labels actions and resources without inventing actor names or success verdicts', () => {
    expect(getAuditActionLabel('settings.update')).toBe('更新设置')
    expect(getAuditActionLabel('custom.unmapped')).toBe('custom.unmapped')
    expect(getAuditActionTone('dataset.create')).toBe('create')
    expect(getAuditActionTone('audit.logs.purge')).toBe('delete')
    expect(
      getAuditResourceLabel({ resource_type: 'dataset', resource_id: 'ds-a', details: { name: '资料库' } }),
    ).toEqual({
      name: '资料库',
      detail: '数据集 · ds-a',
    })
    expect(getAuditResourceLabel({ resource_type: null, resource_id: null, details: {} }).name).toBe('未绑定资源')
  })

  it('reads JSON errors returned as blobs instead of reporting a successful export', async () => {
    const config = { headers: new AxiosHeaders() }
    const error = new AxiosError('Request failed', 'ERR_BAD_RESPONSE', config, undefined, {
      status: 403,
      statusText: 'Forbidden',
      headers: new AxiosHeaders(),
      config,
      data: new Blob([JSON.stringify({ detail: '当前账号不能导出' })], { type: 'application/json' }),
    })
    expect(await formatAuditError(error, '导出失败')).toContain('当前账号不能导出')
  })
})
