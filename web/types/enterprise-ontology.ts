import type { OpenApiSchema } from './backend'
import type { OpenApiHeaderParams, OpenApiOkResponse, OpenApiQueryParams } from './openapi-helpers'

export type EnterpriseOntologyDefinitionInput = OpenApiSchema<'OntologyDefinition-Input'>
export type EnterpriseOntologyDefinitionOutput = OpenApiSchema<'OntologyDefinition-Output'>
export type EnterpriseOntologyWorkspaceResponse = OpenApiSchema<'OntologyDraftView'>
export type EnterpriseOntologyVersionResponse = OpenApiSchema<'OntologyVersionView'>
export type EnterpriseOntologyAsset = OpenApiSchema<'AssetDescription'>
export type EnterpriseOntologySuggestionResponse = OpenApiSchema<'OntologySuggestion'>
export type EnterpriseOntologyBindingPreview = OpenApiSchema<'BindingPreview'>
export type EnterpriseOntologyExtractionPreview = OpenApiSchema<'ChunkPreview'>
export type EnterpriseOntologyDraftUpdateRequest = OpenApiSchema<'OntologyDraftUpdate'>
export type EnterpriseOntologyPublishRequest = OpenApiSchema<'OntologyPublishRequest'>
export type EnterpriseOntologyImportRequest = OpenApiSchema<'OntologyImportRequest'>
export type EnterpriseOntologySuggestionRequest = OpenApiSchema<'SuggestionRequest'>
export type EnterpriseOntologyPreviewRequest = OpenApiSchema<'OntologyPreviewRequest'>
type EnterpriseOntologyDocumentPreviewSource = Extract<EnterpriseOntologyPreviewRequest['source'], { kind: 'document' }>
export type EnterpriseOntologyPreviewInput = Omit<EnterpriseOntologyPreviewRequest, 'source'> & {
  source:
    | Exclude<EnterpriseOntologyPreviewRequest['source'], { kind: 'document' }>
    | (Omit<EnterpriseOntologyDocumentPreviewSource, 'limit'> &
        Partial<Pick<EnterpriseOntologyDocumentPreviewSource, 'limit'>>)
}
export type EnterpriseOntologyDocumentRequest = OpenApiSchema<'OntologyDocumentRequest'>
export type EnterpriseOntologyPreparedDocument = OpenApiSchema<'OntologyDocumentView'>
export type EnterpriseOntologyDatasetBinding = OpenApiSchema<'DatasetOntologyView'>
export type EnterpriseOntologyDocumentGraph = Omit<OpenApiSchema<'OntologyDocumentGraph'>, 'object_types'> & {
  object_types: Record<
    string,
    Omit<OpenApiSchema<'ObjectDefinition'>, 'properties'> & { properties: Record<string, EnterpriseOntologyProperty> }
  >
}
export type EnterpriseOntologyGraphEdit = OpenApiSchema<'OntologyGraphEditRequest'>
export type EnterpriseOntologyGraphChanges = OpenApiSchema<'OntologyGraphChanges'>
export type EnterpriseOntologyQuestion = OpenApiSchema<'OntologyQuestion'>
export type EnterpriseOntologyAnswer = OpenApiSchema<'OntologyAnswer'>
export type EnterpriseOntologyKnowledgeQuestion = OpenApiSchema<'OntologyKnowledgeQuestion'>
export type EnterpriseOntologyDocumentDraftRequest = OpenApiSchema<'DocumentDraftRequest'>
export type EnterpriseOntologyDocumentDraft = OpenApiSchema<'DocumentDraftView'>
export type EnterpriseOntologyMetadataReviewRequest = OpenApiSchema<'DocumentMetadataReview'>
export type EnterpriseOntologyMetadataField = OpenApiSchema<'DocumentMetadataField'>
export type EnterpriseOntologyMetadataStatus = OpenApiSchema<'DocumentMetadataStatus'>
export type EnterpriseOntologySourceSpan = Pick<
  OpenApiSchema<'ManualMetadataValue'>,
  'chunk_id' | 'start_char' | 'end_char'
>
export type EnterpriseOntologyMetadata = OpenApiOkResponse<
  '/api/v1/kg/ontologies/{ontology_id}/versions/{version_id}/documents/{document_id}/metadata',
  'get'
>
export type EnterpriseOntologyMetadataQuery = NonNullable<
  OpenApiQueryParams<
    '/api/v1/kg/ontologies/{ontology_id}/versions/{version_id}/documents/{document_id}/metadata',
    'get'
  >
>
export type EnterpriseOntologyAssetsQuery = NonNullable<OpenApiQueryParams<'/api/v1/kg/ontologies/assets', 'get'>>
export type EnterpriseOntologyHeaders = NonNullable<OpenApiHeaderParams<'/api/v1/kg/ontologies', 'get'>>
export type EnterpriseOntologyActionInput = OpenApiSchema<'ActionInput'>
export type EnterpriseOntologyRuleCandidate = OpenApiSchema<'OntologyRuleCandidate'>
export type EnterpriseOntologyWorkflowInput = OpenApiSchema<'WorkflowInput'>
export type EnterpriseOntologyWorkflowView = OpenApiSchema<'WorkflowView'>
export type OntologyActionProposal = OpenApiSchema<'OntologyActionProposal'>
export type EnterpriseOntologyAction = OpenApiSchema<'ActionView'>
export type EnterpriseOntologyEdoProvenance = OpenApiSchema<'EdoProvenance'>
export type EnterpriseOntologyMetric = OpenApiSchema<'MetricResult'>
export type EnterpriseOntologyObject = OpenApiSchema<'BusinessObject'>
export type EnterpriseOntologyProperty = OpenApiSchema<'PropertyDefinition'>
export type EnterpriseOntologyPropertyInputView = Omit<EnterpriseOntologyProperty, 'required' | 'multiple'> &
  Partial<Pick<EnterpriseOntologyProperty, 'required' | 'multiple'>>
export type EnterpriseOntologyRelation = OpenApiSchema<'RelationDefinition'>

// These endpoints serialize Pydantic response models, including their default_factory values.
// Read views express those emitted fields without adding defaults or modifying response data.
export type EnterpriseOntologyAssetView = EnterpriseOntologyAsset & Required<Pick<EnterpriseOntologyAsset, 'columns'>>
export type EnterpriseOntologyBindingPreviewView = EnterpriseOntologyBindingPreview &
  Required<Pick<EnterpriseOntologyBindingPreview, 'sample' | 'issues' | 'row_count' | 'truncated'>>
export type EnterpriseOntologyExtractionPreviewView = EnterpriseOntologyExtractionPreview &
  Required<Pick<EnterpriseOntologyExtractionPreview, 'page' | 'entities' | 'relations' | 'rejected'>>
type EnterpriseOntologyMetricQueryView = OpenApiSchema<'MetricQuery'> &
  Required<Pick<OpenApiSchema<'MetricQuery'>, 'filters'>>
export type EnterpriseOntologyMetricView = Omit<EnterpriseOntologyMetric, 'query'> & {
  query: EnterpriseOntologyMetricQueryView
}
type EnterpriseOntologyCitationView = OpenApiSchema<'OntologyCitation'> &
  Required<Pick<OpenApiSchema<'OntologyCitation'>, 'metadata'>>
type EnterpriseOntologyFunctionView = Omit<OpenApiSchema<'FunctionResult'>, 'result'> & {
  result: EnterpriseOntologyMetricView
}
export type EnterpriseOntologyAnswerView = Omit<EnterpriseOntologyAnswer, 'metric' | 'function' | 'citations'> &
  Required<Pick<EnterpriseOntologyAnswer, 'conflicts' | 'unavailable'>> & {
    metric?: EnterpriseOntologyMetricView | null
    function?: EnterpriseOntologyFunctionView | null
    citations: EnterpriseOntologyCitationView[]
  }
export type EnterpriseOntologyKnowledgeAnswer = Omit<OpenApiSchema<'OntologyKnowledgeAnswer'>, 'ontology'> & {
  ontology: EnterpriseOntologyAnswerView
}
export type EnterpriseOntologyActionView = Omit<EnterpriseOntologyAction, 'inputs'> & {
  inputs: EnterpriseOntologyActionInput & Required<Pick<EnterpriseOntologyActionInput, 'parameters'>>
}

// SemanticId-keyed patternProperties have generated child schemas, but typegen adds unknown.
// These application views retain those child contracts and the editor's supported shorthand.
export type EnterpriseOntologyObjectDefinitionView = Omit<OpenApiSchema<'ObjectDefinition'>, 'properties'> & {
  properties: Record<string, EnterpriseOntologyProperty['type'] | EnterpriseOntologyPropertyInputView>
}
export type EnterpriseOntologyBindingView = Omit<OpenApiSchema<'ObjectBinding'>, 'columns' | 'identity_columns'> & {
  columns: Record<string, string | OpenApiSchema<'ColumnMapping'>>
  identity_columns: NonNullable<OpenApiSchema<'ObjectBinding'>['identity_columns']>
}
export type EnterpriseOntologyActionDefinitionView = Omit<OpenApiSchema<'ActionDefinition'>, 'parameters'> & {
  parameters: Record<string, EnterpriseOntologyProperty>
}
export type EnterpriseOntologyDocumentTemplateView = Omit<OpenApiSchema<'DocumentTemplate'>, 'fields'> & {
  fields: Record<string, OpenApiSchema<'DocumentField'>>
}
export type EnterpriseOntologyDefinitionView = Omit<
  EnterpriseOntologyDefinitionOutput,
  | 'object_types'
  | 'relations'
  | 'bindings'
  | 'metrics'
  | 'rules'
  | 'functions'
  | 'actions'
  | 'action_workflows'
  | 'document_templates'
  | 'document_metadata'
> & {
  object_types: Record<string, EnterpriseOntologyObjectDefinitionView>
  relations: Record<string, EnterpriseOntologyRelation>
  bindings: EnterpriseOntologyBindingView[]
  metrics?: Record<string, OpenApiSchema<'MetricDefinition'>>
  rules?: Record<string, OpenApiSchema<'RuleDefinition'>>
  functions?: Record<string, OpenApiSchema<'FunctionDefinition'>>
  actions?: Record<string, EnterpriseOntologyActionDefinitionView>
  action_workflows?: Record<string, OpenApiSchema<'ActionWorkflowDefinition'>>
  document_templates?: Record<string, EnterpriseOntologyDocumentTemplateView>
  document_metadata?: Record<string, EnterpriseOntologyMetadataField>
}
export type EnterpriseOntologyWorkspaceView = Omit<EnterpriseOntologyWorkspaceResponse, 'draft'> & {
  draft: EnterpriseOntologyDefinitionView
}
export type EnterpriseOntologyVersionView = Omit<EnterpriseOntologyVersionResponse, 'definition'> & {
  definition: EnterpriseOntologyDefinitionView
}
export type EnterpriseOntologySuggestionView = Omit<EnterpriseOntologySuggestionResponse, 'definition' | 'sources'> & {
  definition: EnterpriseOntologyDefinitionView
  sources: EnterpriseOntologyAssetView[]
}
