import { expect, test } from '@playwright/test'
import { memberFixture, memberShot, openMembers } from './members-table.helpers'

test('phone header entries retain their names and return keyboard focus', async ({ page }) => {
  await memberFixture(page); await page.setViewportSize({ width: 390, height: 844 }); await openMembers(page)
  const help = page.getByRole('button', { name: '角色说明', exact: true }), identity = page.getByRole('button', { name: '身份接入', exact: true })
  await expect(help).toBeVisible()
  await expect(identity).toBeVisible()
  await help.click(); await expect(page.getByRole('dialog', { name: '角色说明', exact: true })).toBeVisible()
  await page.keyboard.press('Escape'); await expect(help).toBeFocused()
  await identity.click(); const dialog = page.getByRole('dialog', { name: '身份接入', exact: true })
  await expect(dialog).toBeVisible(); await memberShot(page, 'final-phone-identity')
  await dialog.getByRole('button', { name: '关闭', exact: true }).click(); await expect(identity).toBeFocused()
})
