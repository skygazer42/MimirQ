import { expect, test, type Page, type Route } from '@playwright/test'

const PLUGIN_NAME = '政务知识插件 E2E'
const PLUGIN_REF = 'plugin:changzhou-gov-service-knowledge@1.0.0:chunk'
const READINESS_ERROR = 'plugin metadata contract failed for answer_detail: required'

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installChunkPreviewPluginReadinessMocks(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    const method = request.method()

    if (pathname === '/api/v1/observability/frontend-vitals' && method === 'POST') {
      return route.fulfill({ status: 204, body: '' })
    }

    if (pathname === '/api/v1/meta' && method === 'GET') {
      return fulfillJson(route, {
        name: 'MimirQ API',
        api_version: 'e2e',
        features: { auth_mode: 'header', vector_backend: 'memory' },
      })
    }

    if (pathname === '/api/v1/pipeline/capabilities' && method === 'GET') {
      return fulfillJson(route, {
        parser_backends: [],
        pdf_backends: [],
        chunk_strategies: ['langchain_recursive'],
        features: {},
      })
    }

    if ((pathname === '/api/v1/datasets' || pathname === '/api/v1/datasets/') && method === 'GET') {
      return fulfillJson(route, {
        items: [],
        total: 0,
      })
    }

    if ((pathname === '/api/v1/documents' || pathname === '/api/v1/documents/') && method === 'GET') {
      return fulfillJson(route, {
        items: [],
        total: 0,
      })
    }

    if ((pathname === '/api/v1/parsing/documents' || pathname === '/api/v1/parsing/documents/') && method === 'GET') {
      return fulfillJson(route, {
        items: [],
        total: 0,
      })
    }

    if (pathname === '/api/v1/pipeline/plugins' && method === 'GET') {
      return fulfillJson(route, {
        items: [
          {
            id: 'changzhou-gov-service-knowledge',
            version: '1.0.0',
            name: PLUGIN_NAME,
            description: 'E2E plugin readiness fixture',
            published: true,
            executable: true,
            test_status: 'passed',
            package_hash: 'abc123def4567890',
            stages: ['chunk'],
            refs: {
              chunk: PLUGIN_REF,
            },
            contract: {
              golden: {
                enabled: false,
              },
            },
            test_report: {
              plugin_id: 'changzhou-gov-service-knowledge',
              version: '1.0.0',
              tested_at: '2026-06-09T00:00:00Z',
            },
          },
        ],
        errors: [],
      })
    }

    if (pathname === '/api/v1/pipeline/plugins/chunk-report' && method === 'POST') {
      const payload = request.postDataJSON() as { plugin_ref?: string }
      expect(payload.plugin_ref).toBe(PLUGIN_REF)
      return fulfillJson(route, {
        schema: 'mimirq.pipeline_plugin_chunk_report.v1',
        generated_at: '2026-06-09T00:00:00Z',
        passed: false,
        plugin: {
          id: 'changzhou-gov-service-knowledge',
          version: '1.0.0',
        },
        summary: {
          governed_records: 2,
          chunks: 0,
          kg_events: 0,
        },
        readiness: {
          status: 'failed',
          checks: [
            {
              name: 'chunk_metadata_contract_valid',
              passed: false,
              value: 2,
              required: true,
              errors: [
                {
                  reason: READINESS_ERROR,
                },
              ],
            },
          ],
        },
        sections: [],
      })
    }

    return fulfillJson(route, {})
  })
}

test('chunk preview surfaces plugin readiness failures from the chunk report', async ({ page }) => {
  await installChunkPreviewPluginReadinessMocks(page)

  await page.goto('/chunk-preview')

  await expect(page.getByRole('heading', { name: '切片预览' })).toBeVisible({
    timeout: 60_000,
  })

  await page.getByText('切块规则').scrollIntoViewIfNeeded()
  await page.getByText('切块规则').locator('..').getByRole('combobox').click()
  await page.getByRole('option', { name: `${PLUGIN_NAME} v1.0.0` }).click()

  const reportCard = page.locator('[data-python-pipeline-plugin-chunk-report]')
  await expect(reportCard).toBeVisible()
  await reportCard.getByRole('button', { name: '生成预检报告' }).click()

  await expect(page.getByText('插件预检报告未通过，请查看契约检查')).toBeVisible()
  await expect(reportCard.getByText('契约检查失败：1 项')).toBeVisible()
  await expect(reportCard.getByText(`chunk_metadata_contract_valid: ${READINESS_ERROR}`)).toBeVisible()
})
