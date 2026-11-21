export type RagasMetricOption = {
  key: string
  label: string
  hint: string
  category: string
  kind: 'RAGAS' | '程序化'
  cost: string
  scopes: Array<'conversation' | 'regression'>
}

const RAGAS_METRIC_OPTIONS: RagasMetricOption[] = [
  {
    key: 'faithfulness',
    label: 'Faithfulness（忠实度）',
    hint: '看答案是否忠于检索上下文',
    category: '忠实度',
    kind: 'RAGAS',
    cost: 'LLM',
    scopes: ['conversation', 'regression'],
  },
  {
    key: 'response_relevancy',
    label: 'Response Relevancy（相关性）',
    hint: '看回答是否真正回应问题',
    category: '相关性',
    kind: 'RAGAS',
    cost: 'LLM',
    scopes: ['conversation', 'regression'],
  },
  {
    key: 'context_precision',
    label: 'Context Precision（无参考）',
    hint: '看引用上下文是否足够精准',
    category: '上下文',
    kind: 'RAGAS',
    cost: 'LLM',
    scopes: ['conversation', 'regression'],
  },
  {
    key: 'atomic_faithfulness',
    label: 'Atomic Faithfulness',
    hint: '按声明支持率估算局部幻觉风险，回归专用',
    category: '忠实度',
    kind: '程序化',
    cost: '低成本',
    scopes: ['regression'],
  },
  {
    key: 'hallucination_rate',
    label: 'Hallucination Rate',
    hint: '由 atomic faithfulness 反推的幻觉率，回归专用',
    category: '忠实度',
    kind: '程序化',
    cost: '低成本',
    scopes: ['regression'],
  },
  {
    key: 'citation_accuracy',
    label: 'Citation Accuracy',
    hint: '引用命中的证据是否属于人工标注来源，回归专用',
    category: '引用归因',
    kind: '程序化',
    cost: '低成本',
    scopes: ['regression'],
  },
  {
    key: 'citation_coverage',
    label: 'Citation Coverage',
    hint: '人工标注证据被引用或召回的覆盖率，回归专用',
    category: '引用归因',
    kind: '程序化',
    cost: '低成本',
    scopes: ['regression'],
  },
  {
    key: 'quote_verifiability',
    label: 'Quote Verifiability',
    hint: '回答中的引号片段能否回查到检索上下文，回归专用',
    category: '引用归因',
    kind: '程序化',
    cost: '低成本',
    scopes: ['regression'],
  },
  {
    key: 'chunk_attribution',
    label: 'Chunk Attribution',
    hint: '回答声明被检索证据支撑的比例，回归专用',
    category: '上下文',
    kind: '程序化',
    cost: '低成本',
    scopes: ['regression'],
  },
  {
    key: 'chunk_utilization',
    label: 'Chunk Utilization',
    hint: '被答案实际使用的 chunk 占比，回归专用',
    category: '上下文',
    kind: '程序化',
    cost: '低成本',
    scopes: ['regression'],
  },
  {
    key: 'noise_sensitivity',
    label: 'Noise Sensitivity',
    hint: '答案被无关上下文干扰的比例，回归专用',
    category: '鲁棒性',
    kind: '程序化',
    cost: '低成本',
    scopes: ['regression'],
  },
  {
    key: 'self_knowledge_ratio',
    label: 'Self Knowledge Ratio',
    hint: '正确但缺少引用支撑的声明比例，回归专用',
    category: '引用归因',
    kind: '程序化',
    cost: '低成本',
    scopes: ['regression'],
  },
  {
    key: 'refusal_correctness',
    label: 'Refusal Correctness',
    hint: '应拒答样例是否正确拒答，回归专用',
    category: '安全合规',
    kind: '程序化',
    cost: '低成本',
    scopes: ['regression'],
  },
]

export function getRagasMetricOptions(scope: 'conversation' | 'regression'): RagasMetricOption[] {
  return RAGAS_METRIC_OPTIONS.filter((item) => item.scopes.includes(scope))
}

export function ragasMetricLabel(key: string): string {
  return RAGAS_METRIC_OPTIONS.find((item) => item.key === key)?.label ?? key
}
