import { apiClient, type ApiRequestOptions } from './core'
import type {
  EnterpriseOntologyActionView,
  EnterpriseOntologyActionInput,
  EnterpriseOntologyAnswerView,
  EnterpriseOntologyAssetView,
  EnterpriseOntologyAssetsQuery,
  EnterpriseOntologyBindingPreviewView,
  EnterpriseOntologyDatasetBinding,
  EnterpriseOntologyDefinitionInput,
  EnterpriseOntologyDefinitionView,
  EnterpriseOntologyDocumentGraph,
  EnterpriseOntologyDocumentDraft,
  EnterpriseOntologyDocumentDraftRequest,
  EnterpriseOntologyDocumentRequest,
  EnterpriseOntologyDraftUpdateRequest,
  EnterpriseOntologyExtractionPreviewView,
  EnterpriseOntologyHeaders,
  EnterpriseOntologyGraphEdit,
  EnterpriseOntologyImportRequest,
  EnterpriseOntologyMetadata,
  EnterpriseOntologyMetadataQuery,
  EnterpriseOntologyMetadataReviewRequest,
  EnterpriseOntologyPreparedDocument,
  EnterpriseOntologyPreviewInput,
  EnterpriseOntologyPublishRequest,
  EnterpriseOntologyQuestion,
  EnterpriseOntologyKnowledgeQuestion,
  EnterpriseOntologyKnowledgeAnswer,
  EnterpriseOntologyRuleCandidate,
  EnterpriseOntologySuggestionRequest,
  EnterpriseOntologySuggestionView,
  EnterpriseOntologyVersionView,
  EnterpriseOntologyWorkspaceView,
  EnterpriseOntologyWorkflowInput,
  EnterpriseOntologyWorkflowView,
} from '@/types/enterprise-ontology'

type EnterpriseOntologyRequestOptions = ApiRequestOptions & { headers?: EnterpriseOntologyHeaders }

export const enterpriseOntologyApi = {
  async listWorkspaces(options?: EnterpriseOntologyRequestOptions): Promise<EnterpriseOntologyWorkspaceView[]> {
    const { data } = await apiClient.get<EnterpriseOntologyWorkspaceView[]>('/kg/ontologies', options)
    return data
  },
  async listAssets(
    params: EnterpriseOntologyAssetsQuery,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyAssetView[]> {
    const { data } = await apiClient.get<EnterpriseOntologyAssetView[]>('/kg/ontologies/assets', { ...options, params })
    return data
  },
  async createWorkspace(
    body: EnterpriseOntologyDefinitionInput,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyWorkspaceView> {
    const { data } = await apiClient.post<EnterpriseOntologyWorkspaceView>('/kg/ontologies', body, options)
    return data
  },
  async updateDraft(
    ontologyId: string,
    body: EnterpriseOntologyDraftUpdateRequest,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyWorkspaceView> {
    const { data } = await apiClient.put<EnterpriseOntologyWorkspaceView>(
      `/kg/ontologies/${ontologyId}/draft`,
      body,
      options,
    )
    return data
  },
  async listVersions(
    ontologyId: string,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyVersionView[]> {
    const { data } = await apiClient.get<EnterpriseOntologyVersionView[]>(
      `/kg/ontologies/${ontologyId}/versions`,
      options,
    )
    return data
  },
  async publishVersion(
    ontologyId: string,
    body: EnterpriseOntologyPublishRequest,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyVersionView> {
    const { data } = await apiClient.post<EnterpriseOntologyVersionView>(
      `/kg/ontologies/${ontologyId}/versions`,
      body,
      options,
    )
    return data
  },
  async validateDefinition(
    body: EnterpriseOntologyImportRequest,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyDefinitionView> {
    const { data } = await apiClient.post<EnterpriseOntologyDefinitionView>('/kg/ontologies/validate', body, options)
    return data
  },
  async suggestDefinition(
    body: EnterpriseOntologySuggestionRequest,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologySuggestionView> {
    const { data } = await apiClient.post<EnterpriseOntologySuggestionView>('/kg/ontologies/suggest', body, options)
    return data
  },
  async previewBindings(
    body: EnterpriseOntologyDefinitionInput,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyBindingPreviewView[]> {
    const { data } = await apiClient.post<EnterpriseOntologyBindingPreviewView[]>(
      '/kg/ontologies/binding-preview',
      body,
      options,
    )
    return data
  },
  async previewExtraction(
    body: EnterpriseOntologyPreviewInput,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyExtractionPreviewView[]> {
    const { data } = await apiClient.post<EnterpriseOntologyExtractionPreviewView[]>(
      '/kg/ontologies/preview',
      body,
      options,
    )
    return data
  },
  async previewRules(body: EnterpriseOntologyPreviewInput): Promise<EnterpriseOntologyRuleCandidate[]> {
    const { data } = await apiClient.post<EnterpriseOntologyRuleCandidate[]>('/kg/ontologies/preview/rules', body)
    return data
  },
  async getActiveDataset(
    datasetId: string,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyDatasetBinding> {
    const { data } = await apiClient.get<EnterpriseOntologyDatasetBinding>(
      `/kg/ontologies/datasets/${datasetId}/active`,
      options,
    )
    return data
  },
  async getDocumentGraph(
    datasetId: string,
    documentId: string,
    chunkId: string | undefined,
    options?: ApiRequestOptions,
  ): Promise<EnterpriseOntologyDocumentGraph> {
    const { data } = await apiClient.get<EnterpriseOntologyDocumentGraph>(
      `/kg/ontologies/datasets/${datasetId}/documents/${documentId}/graph`,
      { ...options, params: { chunk_id: chunkId } },
    )
    return data
  },
  async editDocumentGraph(
    datasetId: string,
    documentId: string,
    chunkId: string,
    body: EnterpriseOntologyGraphEdit,
  ): Promise<EnterpriseOntologyDocumentGraph> {
    const { data } = await apiClient.put<EnterpriseOntologyDocumentGraph>(
      `/kg/ontologies/datasets/${datasetId}/documents/${documentId}/graph/${chunkId}`,
      body,
    )
    return data
  },
  async prepareDocument(
    ontologyId: string,
    versionId: string,
    body: EnterpriseOntologyDocumentRequest,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyPreparedDocument> {
    const { data } = await apiClient.post<EnterpriseOntologyPreparedDocument>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/documents`,
      body,
      options,
    )
    return data
  },
  async activateDataset(
    ontologyId: string,
    versionId: string,
    datasetId: string,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyDatasetBinding> {
    const { data } = await apiClient.put<EnterpriseOntologyDatasetBinding>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/datasets/${datasetId}`,
      undefined,
      options,
    )
    return data
  },
  async askVersion(
    ontologyId: string,
    versionId: string,
    body: EnterpriseOntologyQuestion,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyAnswerView> {
    const { data } = await apiClient.post<EnterpriseOntologyAnswerView>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/ask`,
      body,
      options,
    )
    return data
  },
  async askKnowledgeVersion(
    ontologyId: string,
    versionId: string,
    body: EnterpriseOntologyKnowledgeQuestion,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyKnowledgeAnswer> {
    const { data } = await apiClient.post<EnterpriseOntologyKnowledgeAnswer>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/ask/knowledge`,
      body,
      options,
    )
    return data
  },
  async createDocumentDraft(
    ontologyId: string,
    versionId: string,
    body: EnterpriseOntologyDocumentDraftRequest,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyDocumentDraft> {
    const { data } = await apiClient.post<EnterpriseOntologyDocumentDraft>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/draft-documents`,
      body,
      options,
    )
    return data
  },
  async getDocumentDraft(
    ontologyId: string,
    versionId: string,
    draftId: string,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyDocumentDraft> {
    const { data } = await apiClient.get<EnterpriseOntologyDocumentDraft>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/draft-documents/${encodeURIComponent(draftId)}`,
      options,
    )
    return data
  },
  async exportDocumentDraft(
    ontologyId: string,
    versionId: string,
    draftId: string,
    final: boolean,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/draft-documents/${draftId}/docx`,
      { ...options, responseType: 'blob', params: final ? { final: true } : undefined },
    )
    return data
  },
  async prepareAction(
    ontologyId: string,
    versionId: string,
    actionId: string,
    body: EnterpriseOntologyActionInput,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyActionView> {
    const { data } = await apiClient.post<EnterpriseOntologyActionView>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/actions/${actionId}/prepare`,
      body,
      options,
    )
    return data
  },
  async advanceAction(
    ontologyId: string,
    versionId: string,
    requestId: string,
    operation: string,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyActionView> {
    const { data } = await apiClient.post<EnterpriseOntologyActionView>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/action-requests/${requestId}/${operation}`,
      undefined,
      options,
    )
    return data
  },
  async getDocumentMetadata(
    ontologyId: string,
    versionId: string,
    documentId: string,
    params?: EnterpriseOntologyMetadataQuery,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyMetadata> {
    const { data } = await apiClient.get<EnterpriseOntologyMetadata>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/documents/${documentId}/metadata`,
      { ...options, params },
    )
    return data
  },
  async createWorkflow(
    ontologyId: string,
    versionId: string,
    workflowId: string,
    body: EnterpriseOntologyWorkflowInput,
  ): Promise<EnterpriseOntologyWorkflowView> {
    const { data } = await apiClient.post<EnterpriseOntologyWorkflowView>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/workflows/${workflowId}/requests`,
      body,
    )
    return data
  },
  async getWorkflow(ontologyId: string, versionId: string, requestId: string): Promise<EnterpriseOntologyWorkflowView> {
    const { data } = await apiClient.get<EnterpriseOntologyWorkflowView>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/workflow-requests/${encodeURIComponent(requestId)}`,
    )
    return data
  },
  async advanceWorkflow(
    ontologyId: string,
    versionId: string,
    requestId: string,
    index: number,
    operation: 'preview' | 'approve' | 'execute' | 'receipt' | 'cancel',
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyWorkflowView> {
    const { data } = await apiClient.post<EnterpriseOntologyWorkflowView>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/workflow-requests/${requestId}/steps/${index}/${operation}`,
      undefined,
      options,
    )
    return data
  },
  async reviewDocumentMetadata(
    ontologyId: string,
    versionId: string,
    documentId: string,
    body: EnterpriseOntologyMetadataReviewRequest,
    params?: EnterpriseOntologyMetadataQuery,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyMetadata> {
    const { data } = await apiClient.put<EnterpriseOntologyMetadata>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/documents/${documentId}/metadata`,
      body,
      { ...options, params },
    )
    return data
  },
  async listDocumentEvidence(
    ontologyId: string,
    versionId: string,
    documentId: string,
    params?: EnterpriseOntologyMetadataQuery,
    options?: EnterpriseOntologyRequestOptions,
  ): Promise<EnterpriseOntologyExtractionPreviewView[]> {
    const { data } = await apiClient.get<EnterpriseOntologyExtractionPreviewView[]>(
      `/kg/ontologies/${ontologyId}/versions/${versionId}/documents/${documentId}/evidence`,
      { ...options, params },
    )
    return data
  },
}
