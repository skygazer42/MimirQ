import { beforeEach, describe, expect, it, vi } from 'vitest'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('@/lib/api/core', () => ({ apiClient: client }))

import { enterpriseOntologyApi } from './enterprise-ontology'
import type {
  EnterpriseOntologyActionInput,
  EnterpriseOntologyDefinitionInput,
  EnterpriseOntologyPreviewInput,
  EnterpriseOntologyPropertyInputView,
} from '@/types/enterprise-ontology'

const ontologyId = '00000000-0000-4000-8000-000000000001'
const versionId = '00000000-0000-4000-8000-000000000002'
const documentId = '00000000-0000-4000-8000-000000000003'
const versionPath = `/kg/ontologies/${ontologyId}/versions/${versionId}`
const headers = { 'X-EDO-Authorization': 'test-edo-value' }

describe('enterprise ontology request contracts', () => {
  beforeEach(() => vi.resetAllMocks())

  it('keeps the selected release and knowledge scope on the fusion endpoint', async () => {
    const signal = new AbortController().signal
    const body = { question: '查询并引用原文。', dataset_ids: [documentId] }
    const result = { answer: '融合回答。', citations: [], ontology: {}, metrics: {} }
    client.post.mockResolvedValueOnce({ data: result })

    await expect(
      enterpriseOntologyApi.askKnowledgeVersion(ontologyId, versionId, body, { signal, headers }),
    ).resolves.toBe(result)
    expect(client.post).toHaveBeenCalledExactlyOnceWith(`${versionPath}/ask/knowledge`, body, { signal, headers })
  })

  it('keeps cancellation and selected asset/dataset scopes on the shared client', async () => {
    const signal = new AbortController().signal
    const active = { dataset_id: documentId, version_id: null }
    client.get
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({ data: active })

    await expect(enterpriseOntologyApi.listWorkspaces({ signal })).resolves.toEqual([])
    await enterpriseOntologyApi.listAssets({ dataset_id: documentId }, { signal })
    await expect(enterpriseOntologyApi.getActiveDataset(documentId, { signal })).resolves.toBe(active)

    expect(client.get).toHaveBeenNthCalledWith(1, '/kg/ontologies', { signal })
    expect(client.get).toHaveBeenNthCalledWith(2, '/kg/ontologies/assets', {
      signal,
      params: { dataset_id: documentId },
    })
    expect(client.get).toHaveBeenNthCalledWith(3, `/kg/ontologies/datasets/${documentId}/active`, { signal })
  })

  it('does not insert optional input defaults or change imported source bytes', async () => {
    const property: EnterpriseOntologyPropertyInputView = { type: 'string' }
    const definition: EnterpriseOntologyDefinitionInput = {
      schema_version: 1,
      ontology: 'maintenance',
      object_types: { equipment: { key: ['id'], properties: { id: property } } },
    }
    const preview: EnterpriseOntologyPreviewInput = {
      definition,
      source: { kind: 'document', document_id: documentId },
    }
    const sample: EnterpriseOntologyPreviewInput = { definition, source: { kind: 'sample', text: '  原文\n\n' } }
    client.post.mockResolvedValue({ data: [] })

    await enterpriseOntologyApi.createWorkspace(definition)
    await enterpriseOntologyApi.previewExtraction(preview)
    await enterpriseOntologyApi.previewExtraction(sample)
    expect(client.post).toHaveBeenNthCalledWith(1, '/kg/ontologies', definition, undefined)
    expect(client.post).toHaveBeenNthCalledWith(2, '/kg/ontologies/preview', preview, undefined)
    expect(client.post).toHaveBeenNthCalledWith(3, '/kg/ontologies/preview', sample, undefined)
    expect(JSON.stringify(preview)).not.toContain('"limit"')
    expect(JSON.stringify(definition)).not.toContain('"required"')
    expect(JSON.stringify(definition)).not.toContain('"multiple"')
    if (sample.source.kind !== 'sample') throw new Error('Expected sample preview source')
    expect(sample.source.text).toBe('  原文\n\n')
  })

  it('preserves draft revision bodies and explicit EDO headers without default credentials', async () => {
    const definition: EnterpriseOntologyDefinitionInput = {
      schema_version: 1,
      ontology: 'maintenance',
      object_types: { equipment: { key: ['id'], properties: { id: 'string' } } },
    }
    const update = { definition, expected_revision: 2 }
    client.put.mockResolvedValue({ data: { id: ontologyId } })
    client.post.mockResolvedValue({ data: { id: versionId } })

    await enterpriseOntologyApi.updateDraft(ontologyId, update)
    await enterpriseOntologyApi.publishVersion(ontologyId, { expected_revision: 2 }, { headers })
    expect(client.put).toHaveBeenCalledExactlyOnceWith(`/kg/ontologies/${ontologyId}/draft`, update, undefined)
    expect(client.post).toHaveBeenCalledExactlyOnceWith(
      `/kg/ontologies/${ontologyId}/versions`,
      { expected_revision: 2 },
      { headers },
    )
  })

  it('preserves activation/action undefined bodies and the callers stable request identity', async () => {
    const body: EnterpriseOntologyActionInput = {
      request_id: documentId,
      key: { id: 'EQ-0' },
      parameters: { enabled: false, threshold: 0 },
    }
    const response = { request_id: documentId, state: 'ready' }
    client.post.mockResolvedValue({ data: response })
    client.put.mockResolvedValue({ data: { dataset_id: documentId, version_id: versionId } })

    await enterpriseOntologyApi.prepareAction(ontologyId, versionId, 'start', body, { headers })
    await enterpriseOntologyApi.prepareAction(ontologyId, versionId, 'start', body, { headers })
    await enterpriseOntologyApi.advanceAction(ontologyId, versionId, documentId, 'execute', { headers })
    await enterpriseOntologyApi.activateDataset(ontologyId, versionId, documentId, { headers })
    expect(client.post).toHaveBeenNthCalledWith(1, versionPath + '/actions/start/prepare', body, { headers })
    expect(client.post).toHaveBeenNthCalledWith(2, versionPath + '/actions/start/prepare', body, { headers })
    expect(client.post).toHaveBeenNthCalledWith(3, versionPath + `/action-requests/${documentId}/execute`, undefined, {
      headers,
    })
    expect(client.put).toHaveBeenCalledExactlyOnceWith(versionPath + `/datasets/${documentId}`, undefined, { headers })
  })

  it('keeps pipeline hashes, abort signals and zero-based manual evidence spans unchanged', async () => {
    const signal = new AbortController().signal
    const params = { pipeline_hash: 'hash-0' }
    const body = {
      field: 'report_date',
      candidate_ids: [],
      manual_values: [{ chunk_id: documentId, start_char: 0, end_char: 12 }],
    }
    const metadata = { report_date: { state: 'pending', candidates: [], confirmed: [] } }
    client.get.mockResolvedValueOnce({ data: metadata }).mockResolvedValueOnce({ data: [] })
    client.put.mockResolvedValueOnce({ data: metadata })

    await expect(
      enterpriseOntologyApi.getDocumentMetadata(ontologyId, versionId, documentId, params, { signal }),
    ).resolves.toBe(metadata)
    await enterpriseOntologyApi.reviewDocumentMetadata(ontologyId, versionId, documentId, body, params)
    await enterpriseOntologyApi.listDocumentEvidence(
      ontologyId,
      versionId,
      documentId,
      { pipeline_hash: undefined },
      { signal },
    )
    expect(client.get).toHaveBeenNthCalledWith(1, versionPath + `/documents/${documentId}/metadata`, { signal, params })
    expect(client.put).toHaveBeenCalledExactlyOnceWith(versionPath + `/documents/${documentId}/metadata`, body, {
      params,
    })
    expect(client.get).toHaveBeenNthCalledWith(2, versionPath + `/documents/${documentId}/evidence`, {
      signal,
      params: { pipeline_hash: undefined },
    })
  })

  it('encodes a supplied draft id once and retains Blob/final transport instead of JSON coercion', async () => {
    const id = 'saved /?id'
    const blob = new Blob(['docx'], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
    client.get.mockResolvedValueOnce({ data: { id } }).mockResolvedValue({ data: blob })

    await enterpriseOntologyApi.getDocumentDraft(ontologyId, versionId, id, { headers })
    await expect(
      enterpriseOntologyApi.exportDocumentDraft(ontologyId, versionId, documentId, false, { headers }),
    ).resolves.toBe(blob)
    await expect(
      enterpriseOntologyApi.exportDocumentDraft(ontologyId, versionId, documentId, true, { headers }),
    ).resolves.toBe(blob)
    expect(client.get).toHaveBeenNthCalledWith(1, versionPath + '/draft-documents/saved%20%2F%3Fid', { headers })
    expect(client.get).toHaveBeenNthCalledWith(2, versionPath + `/draft-documents/${documentId}/docx`, {
      headers,
      responseType: 'blob',
      params: undefined,
    })
    expect(client.get).toHaveBeenNthCalledWith(3, versionPath + `/draft-documents/${documentId}/docx`, {
      headers,
      responseType: 'blob',
      params: { final: true },
    })
  })

  it('propagates the same request failures instead of manufacturing empty or successful data', async () => {
    const failure = new Error('request rejected')
    client.get.mockRejectedValueOnce(failure)
    client.post.mockRejectedValueOnce(failure)
    await expect(enterpriseOntologyApi.listWorkspaces()).rejects.toBe(failure)
    await expect(
      enterpriseOntologyApi.askVersion(ontologyId, versionId, { question: '状态？' }, { headers }),
    ).rejects.toBe(failure)
  })
})
