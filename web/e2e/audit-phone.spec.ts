import { expect, test } from '@playwright/test'
import { auditEvidence, auditFixture, openAudit, waitAudit } from './audit-table.helpers'

test('phone fixed columns leave the resource label and identifier exposed at the right edge', async ({ page }) => {
  const state = await auditFixture(page)
  state.rows[0] = { ...state.rows[0], resource_type: 'settings', resource_id: 'env', details: {} }
  await page.setViewportSize({ width: 390, height: 844 }); await openAudit(page); await waitAudit(page)
  const scroll = page.getByRole('region', { name: '审计记录表，可横向滚动', exact: true })
  await scroll.evaluate(element => { element.scrollLeft = element.scrollWidth })
  const row = scroll.locator('tbody tr').first()
  const geometry = await row.evaluate(element => {
    const cells = Array.from(element.querySelectorAll('td')).filter(cell => getComputedStyle(cell).display !== 'none')
    const timeRight = cells[1].getBoundingClientRect().right, resource = cells[3]
    const label = resource.querySelector('small')!
    const range = document.createRange(); range.selectNodeContents(label)
    return { timeRight, idLeft: range.getBoundingClientRect().left, resourceLeft: resource.getBoundingClientRect().left }
  })
  expect(geometry.idLeft).toBeGreaterThanOrEqual(geometry.timeRight)
  await expect(page.getByText('左右滑动查看表格，更多信息见明细', { exact: true })).toBeVisible()
  const headerButtons = page.locator('[data-audit-table] > header').getByRole('button')
  for (const button of await headerButtons.all()) {
    const rect = await button.boundingBox()
    expect(rect?.width).toBeGreaterThanOrEqual(44)
    expect(rect?.height).toBeGreaterThanOrEqual(44)
  }
  await page.screenshot({ path: `${auditEvidence}/phone-right-edge.png` })
  await page.setViewportSize({ width: 320, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
})
