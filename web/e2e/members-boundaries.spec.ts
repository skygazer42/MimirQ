import fs from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import { memberEvidence, memberFixture, memberShot, openMembers, pickRole } from './members-table.helpers'

test('confirmed self-demotion removes write controls after access readback', async ({ page }) => {
  const state = await memberFixture(page); await openMembers(page)
  await pickRole(page, '林澈', '查看者')
  const dialog = page.getByRole('alertdialog', { name: '修改自己的角色？', exact: true })
  await dialog.getByRole('button', { name: '修改我的角色', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('combobox', { name: /^角色 / })).toHaveCount(0)
  expect(state.writes).toEqual([{ path: '/api/v1/rbac/members/member-owner', method: 'PATCH', body: { role: 'viewer' } }])
  expect(state.canManage).toBe(false); expect(state.errors).toEqual([]); expect(state.blocked).toEqual([])
})

test('missing account associations and external identities remain honest and noneditable', async ({ page }) => {
  const state = await memberFixture(page)
  state.canManage = false
  state.members = [
    { ...state.members[0], id: 'external-record', user_id: 'external-subject@company.org', username: null, email: null, role: 'new-role' },
    { ...state.members[1], id: 'unlinked-record', user_id: null, username: null, email: null, role: '' },
  ]
  await openMembers(page)
  await expect(page.getByRole('table')).toContainText('external-subject@company.org')
  await expect(page.getByRole('table')).toContainText('new-role')
  await expect(page.getByRole('table')).toContainText('未分配角色')
  await page.getByRole('button', { name: '成员操作 未关联账号', exact: true }).click()
  await expect(page.getByRole('menu')).toContainText('暂无可用操作')
  await expect(page.getByRole('menuitem', { name: '移除成员', exact: true })).toHaveCount(0)
  expect(state.writes).toEqual([]); expect(state.errors).toEqual([])
})

test('capture representative live component snapshots for static visual evidence', async ({ page }) => {
  await memberFixture(page); await openMembers(page)
  const saveSnapshot = async (name: string) => {
    const html = (await page.content()).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/\b(href|src)="\/(?!\/)/g, '$1="http://127.0.0.1:3000/')
    fs.mkdirSync(memberEvidence, { recursive: true }); fs.writeFileSync(path.join(memberEvidence, `${name}.html`), html)
  }
  await memberShot(page, 'final-desktop'); await saveSnapshot('desktop-rendered')
  await page.getByRole('button', { name: '角色说明', exact: true }).click()
  await memberShot(page, 'final-role-help')
  await page.keyboard.press('Escape')
  await page.setViewportSize({ width: 390, height: 844 }); await openMembers(page)
  await memberShot(page, 'final-phone'); await saveSnapshot('phone-rendered')
})
