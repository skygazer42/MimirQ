import { expect, test, type Page } from '@playwright/test'
import type { EnterpriseOntologyAnswerView, EnterpriseOntologyMetricView } from '../types/enterprise-ontology'
import { promptFixture } from './prompts-table.helpers'

const ontologyId = '24f201cb-9b5e-4fea-b898-15e884cfa28f'
const firstVersion = 'ec8c2bef-7c6e-4404-8077-b56ab067aaec'
const secondVersion = 'dc9af42f-de4b-4507-afc1-c94f8286e7ce'
const datasetId = 'e27960d0-fc1c-4f1b-adfd-e7df4be33852'
const documentId = '29579bdc-92ce-4a2b-b676-61b3889fe36d'
const draftId = '99b8585d-32bd-44c2-aba8-ed83caabf724'
const metadataCandidate = '818ed93c-6f0c-4b8d-ba84-73359230fe0d'
const base = '/api/v1/kg/ontologies'
const versionPath = `${base}/${ontologyId}/versions/${firstVersion}`
const definition = {
  schema_version: 1,
  ontology: 'maintenance',
  object_types: { equipment: { key: ['id'], properties: { id: 'string' } } },
  relations: {},
  bindings: [],
}

async function openOntology(page: Page) {
  await page.goto('/ontology', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '企业本体', exact: true })).toBeVisible({ timeout: 60000 })
  const workspace = page.getByRole('region', { name: '企业本体工作台', exact: true })
  await expect(workspace.getByRole('combobox', { name: '本体草稿', exact: true })).toBeEnabled()
  return workspace
}

test('ontology failures remain retryable and a genuine empty tenant can start modeling', async ({ page }) => {
  await promptFixture(page)
  let fail = true
  await page.route(/\/api\/v1\/kg\/ontologies$/, (route) =>
    route.fulfill(fail ? { status: 503, json: { detail: '本体服务暂不可用' } } : { json: [] }),
  )
  await page.goto('/ontology')
  await expect(page.getByRole('heading', { name: '企业本体加载失败' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '还没有企业本体' })).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: '重新加载', exact: true }).click()
  await expect(page.getByRole('heading', { name: '还没有企业本体' })).toBeVisible()
  await expect(page.getByText('统一管理业务对象、数据映射与可执行规则。', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '导入或从资产生成', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '企业本体', exact: true })).toHaveAttribute('aria-current', 'page')
  await page.getByRole('button', { name: '新建本体', exact: true }).click()
  const directory = page.getByRole('navigation', { name: '本体资产类型' })
  await expect(directory.locator('button[data-current]')).toHaveCount(11)
  for (const label of [
    '对象',
    '关系',
    '数据绑定',
    '指标',
    '规则',
    '函数',
    '动作',
    '动作流程',
    '文档元数据',
    '知识概念',
    '文书模板',
  ]) {
    await directory.getByRole('button', { name: label, exact: true }).click()
    await expect(directory.getByRole('button', { name: label, exact: true })).toHaveAttribute('data-current', 'true')
  }
  await directory.getByRole('button', { name: '对象', exact: true }).click()
  await page.getByRole('textbox', { name: '新对象标识' }).fill('equipment')
  await page.getByRole('button', { name: '添加对象', exact: true }).click()
  const lineage = page.getByRole('region', { name: '六层语义血缘' })
  for (const label of ['数据层', '业务对象层', '关系层', '指标层', '规则层', '函数与动作层'])
    await expect(lineage.getByText(label, { exact: true })).toBeVisible()
  await lineage
    .getByRole('button', { name: /未配置/ })
    .first()
    .click()
  await expect(page.getByRole('button', { name: '添加绑定', exact: true })).toBeVisible()
})

test('reviews a quoted rule candidate and saves it through the existing draft flow', async ({ page }) => {
  await promptFixture(page)
  const quote = '设备标识为 E102 时属于本次检修范围。'
  const rule = {
    object_type: 'equipment',
    label: '检修范围',
    conditions: [{ property: 'id', operator: 'eq', value: 'E102' }],
  }
  const initialDefinition = {
    ...definition,
    bindings: [
      {
        object_type: 'equipment',
        role: 'primary',
        asset_id: 'equipment',
        identity_columns: ['id'],
        columns: { id: 'id' },
      },
    ],
  }
  let saves = 0
  await page.route(/\/kg\/ontologies(?:\/|$)/, async (route) => {
    const endpoint = new URL(route.request().url()).pathname
    if (endpoint.endsWith('/preview/rules')) {
      expect(route.request().postDataJSON().source).toEqual({ kind: 'sample', text: quote })
      await route.fulfill({
        json: [
          {
            id: 'maintenance_scope',
            rule,
            chunk_id: documentId,
            page: null,
            evidence: { quote, start_char: 0, end_char: quote.length, source: 'quote' },
          },
        ],
      })
    } else if (endpoint.endsWith('/draft')) {
      saves++
      const draft = route.request().postDataJSON().definition
      expect(draft.rules).toEqual({ maintenance_scope: rule })
      await route.fulfill({ json: { id: ontologyId, code: 'maintenance', draft, draft_revision: 2 } })
    } else if (endpoint.endsWith('/versions')) {
      await route.fulfill({ json: [] })
    } else {
      await route.fulfill({
        json: [{ id: ontologyId, code: 'maintenance', draft_revision: 1, draft: initialDefinition }],
      })
    }
  })

  const dialog = await openOntology(page)
  await dialog.getByRole('combobox', { name: /本体/ }).selectOption(ontologyId)
  await expect(dialog.getByRole('textbox', { name: '本体标识', exact: true })).toHaveCount(0)
  await dialog.getByRole('tab', { name: '校验', exact: true }).click()
  await dialog.getByRole('textbox', { name: '或输入抽取样本文本' }).fill(quote)
  await dialog.getByRole('button', { name: '提取规则候选' }).click()
  const candidates = dialog.getByRole('region', { name: '规则候选' })
  await expect(candidates.getByText(quote)).toBeVisible()
  await candidates.getByText('查看规则条件').click()
  await expect(candidates.getByText(/"value": "E102"/)).toBeVisible()
  await candidates.getByRole('button', { name: '加入草稿', exact: true }).click()
  await expect(candidates.getByRole('button', { name: '已加入草稿' })).toBeDisabled()
  expect(saves).toBe(0)
  await dialog.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText('草稿已保存')
  expect(saves).toBe(1)
})

test('enterprise ontology can be authored, saved and published from its independent studio', async ({ page }) => {
  await promptFixture(page)
  let stored: { id: string; code: string; draft: unknown; draft_revision: number } | null = null
  let published: object | null = null
  await page.route(/\/kg\/ontologies(?:\/|$)/, async (route) => {
    const request = route.request()
    if (request.url().endsWith('/versions')) {
      if (request.method() === 'POST') {
        expect(request.postDataJSON().expected_revision).toBe(1)
        published = { id: firstVersion, number: 1, draft_revision: 1, definition: stored?.draft }
        await route.fulfill({ json: published, status: 201 })
      } else {
        await route.fulfill({ json: published ? [published] : [] })
      }
      return
    }
    if (request.method() === 'POST') {
      const draft = request.postDataJSON()
      expect(draft.object_types.equipment.key).toEqual(['id'])
      stored = { id: ontologyId, code: draft.ontology, draft, draft_revision: 1 }
      await route.fulfill({ json: stored, status: 201 })
    } else {
      await route.fulfill({ json: stored ? [stored] : [] })
    }
  })

  const dialog = await openOntology(page)
  await dialog.getByRole('button', { name: '新建本体', exact: true }).click()
  await dialog.getByRole('textbox', { name: '本体标识' }).fill('maintenance')
  await dialog.getByRole('textbox', { name: '新对象标识' }).fill('equipment')
  await dialog.getByRole('button', { name: '添加对象', exact: true }).click()
  await dialog.getByRole('textbox', { name: '对象显示名' }).fill('设备')
  await dialog.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText('草稿已保存')
  await dialog.getByRole('button', { name: '发布版本', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText('已发布版本 1')
  await dialog.getByRole('tab', { name: '运行应用', exact: true }).click()
  await expect(dialog.getByRole('heading', { name: '版本运行', exact: true })).toBeVisible()
  await expect(dialog.getByRole('combobox', { name: '发布版本', exact: true })).toContainText('版本 1 · 草稿修订 1')
})

test('published metric previews distinguish grouped results from empty or unavailable data', async ({ page }) => {
  await promptFixture(page)
  const dimensions = ['workshop', 'critical']
  const publishedDefinition = {
    ...definition,
    object_types: {
      equipment: {
        ...definition.object_types.equipment,
        properties: {
          id: 'string',
          workshop: { type: 'string', label: '车间' },
          critical: { type: 'boolean', label: '关键设备' },
        },
      },
    },
    metrics: {
      overdue: {
        object_type: 'equipment',
        property: 'id',
        aggregate: 'count',
        label: '逾期工单数',
        dimensions,
      },
    },
  }
  let groupedAnswer =
    '在当前数据覆盖范围内，逾期工单数的分组结果如下。\n\n| 车间 | 关键设备 | 逾期工单数 |\n| --- | --- | --- |\n| 装配 | False | 2 |\n| 质检 | 未登记 | 0 |'
  let groups: EnterpriseOntologyMetricView['groups'] = [
    { dimensions: { workshop: '装配', critical: false }, value: 2 },
    { dimensions: { workshop: '质检', critical: null }, value: 0 },
  ]
  let complete = false
  let reason: string | null = 'source_truncated'
  await page.route(/\/api\/v1\/datasets\/?\?/, (route) => route.fulfill({ json: { items: [], total: 0 } }))
  await page.route(/\/api\/v1\/kg\/ontologies(?:\/|$)/, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/versions')) {
      return route.fulfill({
        json: [{ id: firstVersion, number: 1, draft_revision: 1, definition: publishedDefinition }],
      })
    }
    if (path.endsWith('/ask')) {
      return route.fulfill({
        json: {
          ontology_version_id: firstVersion,
          answer: groupedAnswer,
          plan: { metric_id: 'overdue', include_object: false, include_documents: false },
          metric: {
            metric: 'overdue',
            value: null,
            groups,
            complete,
            reason,
            asset_id: 'ops.work_orders',
            source_updated_at: null,
            query: { filters: {}, group_by: dimensions, historical_state: false },
          },
          citations: [],
          conflicts: [],
          unavailable: [],
        } satisfies EnterpriseOntologyAnswerView,
      })
    }
    return route.fulfill({ json: [{ id: ontologyId, code: 'maintenance', draft: definition, draft_revision: 1 }] })
  })

  const dialog = await openOntology(page)
  await dialog.getByRole('tab', { name: '运行应用', exact: true }).click()
  await expect(dialog.getByRole('tab', { name: '运行应用', exact: true })).toHaveAttribute('aria-selected', 'true')
  await dialog.getByRole('combobox', { name: '本体草稿' }).selectOption(ontologyId)
  await dialog.getByRole('combobox', { name: '发布版本' }).selectOption(firstVersion)
  const applications = dialog.getByRole('tablist', { name: '本体应用' })
  await expect(applications.getByRole('tab', { name: '本体＋知识库问答', exact: true })).toBeVisible()
  await expect(applications.getByRole('tab', { name: '执行', exact: true })).toBeVisible()
  await applications.getByRole('tab', { name: '问数', exact: true }).click()
  const preview = dialog.getByRole('region', { name: '问数', exact: true })
  await expect(preview.getByRole('combobox', { name: '添加问答知识库' })).toHaveCount(0)
  const ask = async (question: string) => {
    await preview.getByRole('textbox', { name: '业务问题' }).fill(question)
    await preview.getByRole('button', { name: '查询数据' }).click()
  }
  await ask('按车间和关键设备统计逾期工单数')
  const table = preview.getByRole('table')
  await expect(table).toHaveCount(1)
  await expect(table.getByRole('columnheader')).toHaveText(['车间', '关键设备', '逾期工单数'])
  await expect(table.getByRole('row', { name: '质检 未登记 0' })).toBeVisible()
  await expect(preview.getByText('车间、关键设备', { exact: true })).toBeVisible()
  await expect(preview.getByText('分组数据覆盖不足')).toBeVisible()
  await expect(preview.getByText('来源数据超出本次扫描上限。')).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await table.scrollIntoViewIfNeeded()
  await expect(table.getByRole('row', { name: '装配 False 2' })).toBeVisible()
  await expect
    .poll(() => preview.evaluate((element) => element.scrollWidth - element.clientWidth))
    .toBeLessThanOrEqual(1)

  groupedAnswer = '逾期工单数在当前授权和筛选条件下没有分组。'
  groups = []
  complete = true
  reason = null
  await ask('按车间和关键设备统计已归档的逾期工单数')
  await expect(preview.getByText('无匹配的分组')).toBeVisible()
  await expect(table).toHaveCount(0)

  groupedAnswer = '所选时间的历史状态不可用。'
  groups = null
  complete = false
  reason = 'historical_state_unavailable'
  await ask('按车间和关键设备统计历史逾期工单数')
  await expect(preview.getByText('分组结果不可用')).toBeVisible()
  await expect(preview.getByText('所选时间的历史数据不可用。')).toBeVisible()
  await expect(table).toHaveCount(0)
})

test('a published version supplies evidence and templates independently of the current draft', async ({ page }) => {
  const fixture = await promptFixture(page)
  const question = '设备 E-102 有几张逾期工单，适用哪份制度？'
  const quote = '设备 E-102 的维修工单按记录的截止时间判定逾期。'
  const draft = {
    id: draftId,
    version_id: firstVersion,
    title: '整改说明',
    markdown: `## 参考依据\n\n${quote}\n\n## 文号\n\n待确认`,
    missing_required: ['reference'],
  }
  let activated = false
  let documentPrepared = false
  let metadataConfirmed = false
  let manualConfirmed = false
  let actionId = ''
  let actionExecutions = 0
  const documentName = 'SLA-2026-11.pdf'
  const activationConflict = `Document ${documentName} (${documentId}) is missing prepared evidence for chunks chunk-a`
  const documentQuote = '制度自 2026-11-01 起生效。'
  const documentCandidate = {
    id: metadataCandidate,
    value: '2026-11-01',
    page: 3,
    evidence: { quote: documentQuote, start_char: 0, end_char: documentQuote.length },
  }
  const actionInputs = { key: { id: 'E-102' }, parameters: { reason: '检查完成' } }
  await page.route(/\/api\/v1\/datasets\/?\?/, (route) =>
    route.fulfill({
      json: {
        items: [{ id: datasetId, name: '维修制度库' }],
        total: 1,
      },
    }),
  )
  await page.route(/\/api\/v1\/documents\/?\?/, (route) => {
    const parameters = new URL(route.request().url()).searchParams
    if (parameters.get('dataset_id') !== datasetId) return route.fallback()
    return route.fulfill({ json: { items: [{ id: documentId, filename: documentName }], total: 1 } })
  })
  await page.route(/\/kg\/ontologies(?:\/|$)/, async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const routeKey = `${request.method()} ${path}`
    switch (routeKey) {
      case `GET ${base}`:
        return route.fulfill({ json: [{ id: ontologyId, code: 'maintenance', draft: definition, draft_revision: 3 }] })
      case `GET ${base}/${ontologyId}/versions`:
        return route.fulfill({
          json: [
            { id: secondVersion, number: 2, draft_revision: 2, definition },
            {
              id: firstVersion,
              number: 1,
              draft_revision: 1,
              definition: {
                ...definition,
                bindings: [{ edo_binding: { endpoint: 'fixture_edo' } }],
                document_metadata: {
                  effective_at: { label: '生效日期', type: 'date' },
                  issuer: { label: '制发单位', type: 'string', method: 'manual' },
                },
                actions: {
                  close: {
                    label: '关闭工单',
                    target: 'case_system',
                    object_type: 'equipment',
                    approval_required: true,
                    parameters: { reason: { type: 'string', label: '原因', required: true } },
                  },
                },
                document_templates: {
                  report: {
                    title: '整改说明',
                    fields: {
                      owner: { label: '发文单位', source: 'manual', required: true },
                      reference: { label: '文号', source: 'manual', required: true },
                    },
                  },
                },
              },
            },
          ],
        })
      case `GET ${base}/datasets/${datasetId}/active`:
        return route.fulfill({ json: { dataset_id: datasetId, version_id: activated ? firstVersion : null } })
      case `POST ${versionPath}/documents`:
        expect(request.postDataJSON()).toEqual({ document_id: documentId })
        documentPrepared = true
        return route.fulfill({
          json: { document_id: documentId, version_id: firstVersion, chunk_count: 3, pipeline_hash: 'parsed-v1' },
        })
      case 'GET ' + versionPath + '/documents/' + documentId + '/metadata':
      case 'PUT ' + versionPath + '/documents/' + documentId + '/metadata':
        expect(new URL(request.url()).searchParams.get('pipeline_hash')).toBe('parsed-v1')
        if (request.method() === 'PUT') {
          const body = request.postDataJSON()
          if (body.field === 'effective_at') {
            expect(body).toEqual({ field: 'effective_at', candidate_ids: [metadataCandidate] })
            metadataConfirmed = true
          } else {
            expect(body).toEqual({
              field: 'issuer',
              candidate_ids: [],
              manual_values: [{ chunk_id: 'chunk-a', start_char: 0, end_char: 3 }],
            })
            manualConfirmed = true
          }
        }
        return route.fulfill({
          json: {
            effective_at: {
              state: metadataConfirmed ? 'confirmed' : 'pending',
              candidates: [documentCandidate],
              confirmed: metadataConfirmed ? [documentCandidate] : [],
            },
            issuer: {
              state: manualConfirmed ? 'confirmed' : 'missing',
              candidates: [],
              confirmed: [],
            },
          },
        })
      case 'GET ' + versionPath + '/documents/' + documentId + '/evidence':
        expect(new URL(request.url()).searchParams.get('pipeline_hash')).toBe('parsed-v1')
        return route.fulfill({ json: [{ chunk_id: 'chunk-a', page: 3 }] })
      case `PUT ${versionPath}/datasets/${datasetId}`:
        if (!documentPrepared) {
          return route.fulfill({ status: 409, json: { error: 'CONFLICT', message: activationConflict } })
        }
        activated = true
        return route.fulfill({ json: { dataset_id: datasetId, version_id: firstVersion } })
      case `POST ${versionPath}/ask/knowledge`:
        expect(request.headers()['x-edo-authorization']).toBe('fixture-edo-session')
        expect(request.postDataJSON()).toEqual({ question, dataset_ids: [datasetId] })
        return route.fulfill({
          json: {
            answer: '本月有 1 张逾期工单，依据已检索的现行维修制度。',
            citations: [
              { document_id: documentId, document_name: documentName, chunk_id: documentId, chunk_content: quote },
            ],
            metrics: { ontology_used: true },
            ontology: {
              ontology_version_id: firstVersion,
              answer: '本月有 1 张逾期工单。',
              metric: {
                metric: 'overdue',
                value: 1,
                complete: true,
                asset_id: 'ops.work_orders',
                source_updated_at: null,
                query: {
                  observed_at: '2026-11-23T20:00:00Z',
                  start: '2026-11-01T00:00:00-07:00',
                  end: '2026-12-01T00:00:00-08:00',
                  filters: { equipment_id: 'E-102' },
                },
              },
              plan: { object_type: 'equipment', business_key: 'E-102', action_id: 'close' },
              citations: [
                {
                  document_id: documentId,
                  filename: documentName,
                  pipeline_hash: 'parsed-v1',
                  chunk_id: 'chunk-a',
                  page: 3,
                  applicability: 'pending',
                  metadata: { effective_at: ['2026-11-01'] },
                  evidence: { quote, start_char: 0, end_char: quote.length },
                },
              ],
              conflicts: ['两份制度的处置时限不一致'],
              unavailable: ['历史快照不可用'],
            },
          },
        })
      case `POST ${versionPath}/draft-documents`:
        expect(request.postDataJSON()).toEqual({
          template_id: 'report',
          question: { question, dataset_ids: [datasetId] },
          manual_fields: { owner: '维修部' },
        })
        return route.fulfill({ json: draft, status: 201 })
      case `GET ${versionPath}/draft-documents/${draftId}`:
        return route.fulfill({
          json: { ...draft, markdown: '## 参考依据\n\n待确认', missing_required: ['reference', 'evidence'] },
        })
      case `GET ${versionPath}/draft-documents/${draftId}/docx`:
        return route.fulfill({
          contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          body: 'example DOCX response',
        })
      case 'POST ' + versionPath + '/actions/close/prepare': {
        const { request_id, ...inputs } = request.postDataJSON()
        expect(inputs).toEqual(actionInputs)
        actionId = request_id
        return route.fulfill({
          json: { request_id, inputs, approved_by: null, receipt: null, state: 'awaiting_approval' },
        })
      }
      case 'POST ' + versionPath + '/action-requests/' + actionId + '/approve':
        return route.fulfill({
          json: {
            request_id: actionId,
            inputs: actionInputs,
            approved_by: 'fixture-user',
            receipt: null,
            state: 'ready',
          },
        })
      case 'POST ' + versionPath + '/action-requests/' + actionId + '/execute':
        actionExecutions++
        return route.fulfill({
          json: {
            request_id: actionId,
            inputs: actionInputs,
            approved_by: 'fixture-user',
            receipt: null,
            state: 'unknown',
          },
        })
      case 'POST ' + versionPath + '/action-requests/' + actionId + '/receipt':
        return route.fulfill({
          json: {
            request_id: actionId,
            inputs: actionInputs,
            approved_by: 'fixture-user',
            state: 'succeeded',
            receipt: { receipt_id: 'receipt-fixture', status: 'succeeded', sync_status: 'pending' },
          },
        })
      default:
        return route.fulfill({ json: { detail: `Unexpected ontology request ${routeKey}` }, status: 400 })
    }
  })

  const dialog = await openOntology(page)
  await dialog.getByRole('combobox', { name: '本体草稿' }).selectOption(ontologyId)
  await dialog.getByRole('tab', { name: '运行应用', exact: true }).click({ timeout: 10000 })
  await dialog.getByRole('combobox', { name: '发布版本' }).selectOption(firstVersion)
  await dialog.getByLabel('EDO 登录凭证').fill('fixture-edo-session')
  await dialog.getByRole('combobox', { name: '准备与激活知识库' }).selectOption(datasetId)
  await expect(dialog.getByText('尚未绑定本体版本')).toBeVisible()
  await dialog.getByRole('button', { name: '激活所选版本' }).click()
  await expect(dialog.getByRole('alert')).toHaveText(activationConflict)
  await expect(dialog.getByText('尚未绑定本体版本')).toBeVisible()
  await dialog.getByRole('combobox', { name: '待准备文档' }).selectOption(documentId)
  await dialog.getByRole('button', { name: '准备文档证据' }).click()
  await expect(dialog.getByText('已准备 3 个分块', { exact: false })).toBeVisible()
  await dialog.getByText('复核文档元数据', { exact: true }).click()
  const metadata = dialog.getByRole('region', { name: '文档元数据' })
  await expect(metadata.getByText(documentQuote, { exact: true })).toBeVisible()
  await expect(metadata.getByText('第 3 页 · 字符 0–' + documentQuote.length)).toBeVisible()
  await metadata.getByRole('checkbox').check()
  await metadata.getByRole('button', { name: '确认选中证据' }).click()
  await expect(metadata.getByText('已确认', { exact: true })).toBeVisible()
  const issuer = metadata.getByRole('group', { name: '制发单位' })
  await issuer.getByText('从原文补录').click()
  await issuer.getByRole('combobox', { name: '原文分块' }).selectOption('chunk-a')
  await issuer.getByLabel('起点字符（从 0 开始）').fill('0')
  await issuer.getByLabel('终点字符（不含）').fill('3')
  await issuer.getByRole('button', { name: '确认原文区间' }).click()
  await expect(issuer.getByText('已确认', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: '激活所选版本' }).click()
  await expect(dialog.getByText('当前生效 · 版本 1')).toBeVisible()

  await dialog.getByRole('tab', { name: '本体＋知识库问答', exact: true }).click()
  await dialog.getByRole('combobox', { name: '添加问答知识库' }).selectOption(datasetId)
  await dialog.getByRole('textbox', { name: '业务问题' }).fill(question)
  await dialog.getByRole('button', { name: '开始问答', exact: true }).click()
  const fusion = dialog.getByRole('region', { name: '融合回答', exact: true })
  await expect(fusion.getByText('本月有 1 张逾期工单，依据已检索的现行维修制度。', { exact: true })).toBeVisible()
  await fusion.getByText('本体证据', { exact: true }).click()
  await expect(fusion.getByText('ops.work_orders')).toBeVisible()
  await expect(fusion.getByText('历史快照不可用')).toBeVisible()
  await expect(fusion.getByText('两份制度的处置时限不一致')).toBeVisible()
  await expect(fusion.getByText('适用性待确认')).toBeVisible()
  await expect(fusion.getByText('生效日期 · 2026-11-01')).toBeVisible()
  await expect(
    dialog.getByRole('region', { name: '引用来源' }).getByRole('link', { name: 'SLA-2026-11.pdf' }),
  ).toHaveAttribute('href', `/chunk-preview?docId=${documentId}`)
  await expect(fusion.getByText(quote, { exact: true })).toBeVisible()
  expect(actionExecutions).toBe(0)

  await dialog.getByRole('combobox', { name: '文书模板' }).selectOption('report')
  await dialog.getByRole('textbox', { name: '发文单位' }).fill('维修部')
  await dialog.getByRole('button', { name: '生成文书草稿' }).click()
  await expect(dialog.getByText('待确认字段 · 文号')).toBeVisible()
  const download = page.waitForEvent('download')
  await dialog.getByRole('button', { name: '下载 DOCX 草稿' }).click()
  expect((await download).suggestedFilename()).toBe('整改说明.docx')
  await dialog.getByRole('button', { name: '重新读取草稿' }).click()
  await expect(dialog.getByText('待确认字段 · 文号、evidence')).toBeVisible()
  await dialog.getByRole('tab', { name: '执行', exact: true }).click()
  await expect(dialog.getByRole('region', { name: '最近问答证据' }).getByText('历史快照不可用')).toBeVisible()
  const actions = dialog.getByRole('region', { name: '业务动作' })
  await actions.getByRole('combobox', { name: '已发布动作' }).selectOption('close')
  await actions.getByRole('textbox', { name: '主键 · id' }).fill('E-102')
  await actions.getByRole('textbox', { name: '参数 · 原因（必填）' }).fill('检查完成')
  await actions.getByRole('button', { name: '预演业务动作' }).click()
  await expect(actions.getByText('关闭工单 · 等待审批')).toBeVisible()
  await expect(actions.getByRole('button', { name: '确认执行业务动作' })).toHaveCount(0)
  await actions.getByRole('button', { name: '审批动作' }).click()
  await expect(actions.getByText('关闭工单 · 待执行')).toBeVisible()
  expect(actionExecutions).toBe(0)
  await actions.getByRole('button', { name: '确认执行业务动作' }).click()
  await expect(actions.getByText('关闭工单 · 结果待核实')).toBeVisible()
  await actions.getByRole('button', { name: '查询动作回执' }).click()
  await expect(actions.getByText('回执 receipt-fixture · 已执行 · 待同步')).toBeVisible()
  expect(actionExecutions).toBe(1)
  await dialog.getByRole('combobox', { name: '发布版本' }).selectOption(secondVersion)
  await expect(dialog.getByText('该版本没有文书模板')).toBeVisible()
  await expect(dialog.getByText('本月有 1 张逾期工单。')).toHaveCount(0)
  expect(fixture.errors).toEqual([])
})

test('advanced definitions are validated before saving and binding previews show mapped samples', async ({ page }) => {
  await promptFixture(page)
  const bindings = [
    {
      object_type: 'equipment',
      role: 'primary',
      asset_id: 'ops.equipment',
      identity_columns: ['asset_id'],
      columns: { id: 'asset_id' },
    },
  ]
  const suggestedAsset = { id: 'ops.equipment', label: '设备档案', kind: 'mysql', columns: ['asset_id'] }
  let stored = { ...definition, bindings }
  let revision = 1
  await page.route(/\/api\/v1\/datasets\/?\?/, (route) =>
    route.fulfill({
      json: {
        items: [{ id: datasetId, name: '维修制度库' }],
        total: 1,
      },
    }),
  )
  await page.route(/\/kg\/ontologies(?:\/|$)/, async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/versions')) return route.fulfill({ json: [] })
    if (path.endsWith('/assets')) {
      expect(new URL(request.url()).searchParams.get('dataset_id')).toBe(datasetId)
      return route.fulfill({ json: [suggestedAsset] })
    }
    if (path.endsWith('/suggest')) {
      expect(request.postDataJSON()).toEqual({
        ontology: 'maintenance',
        dataset_id: datasetId,
        asset_ids: ['ops.equipment'],
        sample: '',
      })
      return route.fulfill({
        json: {
          definition: {
            ...stored,
            object_types: { equipment: { ...stored.object_types.equipment, label: '设备档案' } },
          },
          sources: [suggestedAsset],
        },
      })
    }
    if (path.endsWith('/validate')) {
      const candidate = JSON.parse(request.postDataJSON().content)
      if (candidate.functions?.overdue?.metric !== 'overdue') {
        return route.fulfill({ json: { detail: 'Unknown metric in function overdue' }, status: 422 })
      }
      return route.fulfill({ json: candidate })
    }
    if (path.endsWith('/binding-preview'))
      return route.fulfill({
        json: [
          {
            object_type: 'equipment',
            role: 'primary',
            asset_id: 'ops.equipment',
            identity_columns: ['asset_id'],
            row_count: 2,
            truncated: true,
            sample: [{ id: 'E-102' }],
            issues: [{ code: 'invalid_value', field: 'id' }],
          },
        ],
      })
    if (request.method() === 'PUT') {
      expect(request.postDataJSON().expected_revision).toBe(1)
      expect(request.postDataJSON().definition.functions).toEqual({ overdue: { metric: 'overdue' } })
      expect(request.postDataJSON().definition.metrics.overdue.dimensions).toEqual(['id'])
      stored = request.postDataJSON().definition
      revision++
    }
    const workspace = { id: ontologyId, code: 'maintenance', draft: stored, draft_revision: revision }
    return route.fulfill({ json: request.method() === 'GET' ? [workspace] : workspace })
  })

  const dialog = await openOntology(page)
  await dialog.getByRole('combobox', { name: '本体草稿' }).selectOption(ontologyId)
  await dialog.getByRole('button', { name: '导入与生成', exact: true }).click()
  const importDialog = page.getByRole('dialog', { name: '导入与生成', exact: true })
  await expect(importDialog.getByText('从资产与样本生成')).toBeVisible()
  await importDialog.getByRole('combobox', { name: '资产知识库' }).selectOption(datasetId)
  await importDialog.getByRole('combobox', { name: '添加参考资产' }).selectOption('ops.equipment')
  await importDialog.getByRole('button', { name: '生成草案' }).click()
  await expect(page.locator('[data-ontology-workbench]').getByLabel('对象显示名', { exact: true })).toHaveValue('')
  await importDialog.getByRole('button', { name: '应用到编辑区' }).click()
  await expect(dialog.getByRole('textbox', { name: '对象显示名' })).toHaveValue('设备档案')
  await dialog
    .getByRole('navigation', { name: '本体资产类型' })
    .getByRole('button', { name: '函数', exact: true })
    .click()
  const editor = dialog.getByRole('textbox', { name: '本体行为与高级定义' })
  await expect(editor).toHaveAccessibleDescription(/dimensions/)
  const candidate = {
    ...definition,
    bindings,
    metrics: { overdue: { object_type: 'equipment', property: 'id', aggregate: 'count', dimensions: ['id'] } },
  }
  await editor.fill(JSON.stringify({ ...candidate, functions: { overdue: { metric: 'unknown' } } }))
  await expect(dialog.getByRole('button', { name: '保存草稿' })).toBeDisabled()
  await dialog.getByRole('button', { name: '校验并应用定义' }).click()
  await expect(dialog.getByRole('alert')).toHaveText('Unknown metric in function overdue')
  await editor.fill(JSON.stringify({ ...candidate, functions: { overdue: { metric: 'overdue' } } }))
  await dialog.getByRole('button', { name: '校验并应用定义' }).click()
  await dialog.getByRole('button', { name: '保存草稿' }).click()
  await expect(dialog.getByRole('status')).toHaveText('草稿已保存 · 修订 2')
  const reopened = await openOntology(page)
  await reopened.getByRole('combobox', { name: '本体草稿' }).selectOption(ontologyId)
  await reopened
    .getByRole('navigation', { name: '本体资产类型' })
    .getByRole('button', { name: '函数', exact: true })
    .click()
  const reopenedEditor = reopened.getByRole('textbox', { name: '本体行为与高级定义' })
  await expect(reopenedEditor).toHaveValue(/"metric": "overdue"/)
  await expect(reopenedEditor).toHaveValue(/"dimensions": \[\s+"id"/)
  await reopened
    .getByRole('navigation', { name: '本体资产类型' })
    .getByRole('button', { name: '数据绑定', exact: true })
    .click()
  await reopened.getByRole('combobox', { name: '资产知识库' }).selectOption(datasetId)
  await reopened.getByRole('combobox', { name: '选择已登记资产' }).selectOption('ops.equipment')
  await reopened.getByRole('button', { name: '预检绑定' }).click()
  await expect(reopened.getByRole('cell', { name: 'E-102' })).toBeVisible()
  await expect(reopened.getByText('id · 值无法转换为声明的类型')).toBeVisible()
  await expect(reopened.getByText('仅显示部分样本')).toBeVisible()
})

test('executes a published workflow in order and reopens it by request ID', async ({ page }) => {
  await promptFixture(page)
  const draft = {
    ...definition,
    actions: {
      check: {
        object_type: 'equipment',
        target: 'maintenance',
        label: '核验设备',
        approval_required: true,
        parameters: {},
      },
      close: { object_type: 'equipment', target: 'maintenance', label: '完成工单', parameters: {} },
    },
    action_workflows: { complete: { label: '结束维修', actions: ['check', 'close'] } },
  }
  const calls: string[] = []
  let id = ''
  let current: number | null = 0
  const states = ['', '']
  const workflow = () => ({
    request_id: id,
    workflow_id: 'complete',
    version_id: firstVersion,
    canceled: false,
    current_step: current,
    steps: ['check', 'close'].map((action_id, index) => ({
      action_id,
      inputs: { request_id: index === 0 ? documentId : draftId, key: { id: 'E102' }, parameters: {} },
      action: states[index]
        ? {
            state: states[index],
            receipt: states[index] === 'succeeded' ? { receipt_id: 'receipt-' + index, sync_status: 'synced' } : null,
          }
        : null,
    })),
  })
  await page.route(/\/kg\/ontologies(?:\/|$)/, async (route) => {
    const request = route.request()
    const endpoint = new URL(request.url()).pathname
    if (endpoint.endsWith('/workflows/complete/requests')) {
      const body = request.postDataJSON()
      expect(body.steps).toEqual([
        { key: { id: 'E102' }, parameters: {} },
        { key: { id: 'E102' }, parameters: {} },
      ])
      id = body.request_id
      await route.fulfill({ json: workflow() })
      return
    }
    if (endpoint.includes('/workflow-requests/')) {
      if (request.method() === 'POST') {
        const parts = endpoint.split('/')
        const index = Number(parts.at(-2))
        const operation = parts.at(-1)
        calls.push(index + ':' + operation)
        if (operation === 'preview') states[index] = index === 0 ? 'awaiting_approval' : 'ready'
        if (operation === 'approve') states[index] = 'ready'
        if (operation === 'execute') {
          states[index] = 'succeeded'
          current = index === 0 ? 1 : null
        }
      }
      await route.fulfill({ json: workflow() })
      return
    }
    await route.fulfill({
      json: endpoint.endsWith('/versions')
        ? [{ id: firstVersion, number: 1, draft_revision: 1, definition: draft }]
        : endpoint === base
          ? [{ id: ontologyId, code: 'maintenance', draft_revision: 1, draft }]
          : [],
    })
  })
  const dialog = await openOntology(page)
  await dialog.getByRole('combobox', { name: '本体草稿' }).selectOption(ontologyId)
  await dialog.getByRole('tab', { name: '运行应用', exact: true }).click()
  await dialog.getByRole('tab', { name: '执行', exact: true }).click()
  const section = dialog.getByRole('region', { name: '动作流程' })
  await section.getByLabel('已发布流程').selectOption('complete')
  for (const label of ['核验设备', '完成工单']) {
    await section.getByRole('group', { name: label }).getByLabel('主键 · id').fill('E102')
  }
  await section.getByRole('button', { name: '创建流程请求' }).click()
  await section.getByRole('button', { name: '预演当前动作' }).click()
  await expect(section.getByText('核验设备 · 等待审批')).toBeVisible()
  await expect(section.getByRole('button', { name: '执行当前动作' })).toHaveCount(0)
  await section.getByRole('button', { name: '审批当前动作' }).click()
  await section.getByRole('button', { name: '执行当前动作' }).click()
  await expect(section.getByText('回执 receipt-0')).toBeVisible()
  await section.getByRole('button', { name: '返回流程选择' }).click()
  await section.getByRole('button', { name: '读取流程请求' }).click()
  await section.getByRole('button', { name: '预演当前动作' }).click()
  await section.getByRole('button', { name: '执行当前动作' }).click()
  await expect(section.getByText('结束维修 · 已完成')).toBeVisible()
  await expect(section.getByText('回执 receipt-1')).toBeVisible()
  expect(calls).toEqual(['0:preview', '0:approve', '0:execute', '1:preview', '1:execute'])
  await page.screenshot({ path: test.info().outputPath('workflow-completed.png') })
})
