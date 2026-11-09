import fs from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'
import { memberFixture, openMembers, reloadMembers } from './members-table.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/members-table-v1/ux-recheck')

for (const viewport of [
  { label: 'desktop', width: 1600, height: 1000 },
  { label: 'narrow', width: 390, height: 844 },
]) {
  test(`independent UX same-path recheck ${viewport.label}`, async ({ page }) => {
    test.setTimeout(240_000)
    fs.mkdirSync(evidence, { recursive: true })
    const state = await memberFixture(page)
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    const events: Record<string, unknown>[] = []
    let phase = 'open-workspace'
    const saveState = () => fs.writeFileSync(path.join(evidence, `${viewport.label}-state.json`), JSON.stringify({
      viewport, phase, events,
      savedRole: state.members.find(member => member.user_id === 'member-viewer-b')?.role,
      writes: state.writes, reads: state.reads, blocked: state.blocked,
      errors: state.errors, scimCalls: state.scimCalls, samlProviders: state.samlProviders,
    }, null, 2))
    const checkpoint = async (name: string, details: Record<string, unknown> = {}) => {
      phase = name
      const snapshot = await page.locator('body').ariaSnapshot()
      events.push({ name, ...details })
      fs.writeFileSync(path.join(evidence, `${viewport.label}-${name}.txt`), snapshot)
      await page.screenshot({ path: path.join(evidence, `${viewport.label}-${name}.png`), animations: 'disabled' })
      saveState()
      console.log(`UX_RECHECK ${viewport.label} ${name} ${JSON.stringify(details)}`)
    }
    try {
      await openMembers(page)
      await checkpoint('01-entry')

      // The first review found these icon controls unnamed on the narrow viewport.
      // Recheck uses their current accessible names, never a positional unnamed button.
      for (const [index, name] of ['角色说明', '身份接入'].entries()) {
        phase = `named-entry-${name}`
        const entry = page.getByRole('button', { name, exact: true })
        await expect(entry).toHaveCount(1)
        await expect(entry).toBeVisible()
        await entry.focus()
        await expect(entry).toBeFocused()
        await page.keyboard.press('Enter')
        const dialog = page.getByRole('dialog', { name, exact: true })
        await expect(dialog).toBeVisible()
        await checkpoint(`0${index + 2}-${index === 0 ? 'role-help' : 'identity-entry'}`)
        await page.keyboard.press('Escape')
        await expect(dialog).toBeHidden()
        await expect(entry).toBeFocused()
        events.push({ name: `${name}-closed`, focusReturned: true })
        saveState()
      }

      phase = 'find-member'
      const search = page.getByRole('searchbox', { name: '搜索成员' })
      const memberRole = page.getByRole('combobox', { name: '角色 顾言', exact: true })
      await search.fill('顾言')
      await expect(memberRole).toBeVisible()
      await expect(memberRole).toContainText('查看者')
      await checkpoint('04-found-member')
      await memberRole.click()
      await checkpoint('05-role-options')
      await page.getByRole('option', { name: '编辑者', exact: true }).click()
      await expect(memberRole).toContainText('编辑者')
      expect(state.members.find(member => member.user_id === 'member-viewer-b')?.role).toBe('editor')
      expect(state.writes).toEqual([{ path: '/api/v1/rbac/members/member-viewer-b', method: 'PATCH', body: { role: 'editor' } }])
      await checkpoint('06-saved-role')

      phase = 'refresh-members'
      const readsBefore = state.reads.length
      await page.getByRole('button', { name: '刷新成员', exact: true }).click()
      await expect.poll(() => state.reads.length).toBeGreaterThan(readsBefore)
      await expect(page.getByRole('button', { name: '刷新成员', exact: true })).toBeEnabled()
      await expect(memberRole).toContainText('编辑者')
      await expect(search).toHaveValue('顾言')
      await checkpoint('07-refreshed-members')

      phase = 'browser-reload'
      await reloadMembers(page)
      const searchAfterReload = await search.inputValue()
      await search.fill('顾言')
      await expect(memberRole).toContainText('编辑者')
      expect(state.members.find(member => member.user_id === 'member-viewer-b')?.role).toBe('editor')
      await checkpoint('08-reloaded-confirmed', { searchAfterReload })

      phase = 'rejected-role-change'
      const filter = page.getByRole('combobox', { name: '筛选角色', exact: true })
      await filter.click()
      await page.getByRole('option', { name: '编辑者', exact: true }).click()
      state.failRole = '租户策略拒绝这次角色变更'
      await memberRole.click()
      await page.getByRole('option', { name: '查看者', exact: true }).click()
      const error = page.getByRole('alert').filter({ hasText: '租户策略拒绝这次角色变更' })
      await expect(error).toBeVisible()
      await expect(error).toContainText('顾言')
      await expect(memberRole).toContainText('编辑者')
      await expect(search).toHaveValue('顾言')
      await expect(filter).toContainText('编辑者')
      await expect(page.getByRole('button', { name: /重试/ })).toBeVisible()
      expect(state.members.find(member => member.user_id === 'member-viewer-b')?.role).toBe('editor')
      expect(state.writes).toEqual([
        { path: '/api/v1/rbac/members/member-viewer-b', method: 'PATCH', body: { role: 'editor' } },
        { path: '/api/v1/rbac/members/member-viewer-b', method: 'PATCH', body: { role: 'viewer' } },
      ])
      await checkpoint('09-rejected-context-preserved')
      expect(state.blocked).toEqual([])
      expect(state.scimCalls).toEqual([])
      expect(state.samlProviders).toEqual([])
      phase = 'complete'
      saveState()
    } catch (error) {
      events.push({ name: 'failed', phase, message: String(error) })
      saveState()
      fs.writeFileSync(path.join(evidence, `${viewport.label}-failure.txt`), await page.locator('body').ariaSnapshot().catch(() => 'No page snapshot available'))
      await page.screenshot({ path: path.join(evidence, `${viewport.label}-failure.png`), animations: 'disabled' }).catch(() => {})
      throw error
    }
  })
}
