import { describe, expect, it } from 'vitest'

import {
  buildChatRequest,
  formatAssistantContent,
  formatGraphStep,
  formatRewriteStep,
  formatRouteStep,
} from './use-chat-formatter'

describe('use-chat formatter helpers', () => {
  it('formats graph progress events into readable copy', () => {
    expect(
      formatGraphStep({
        event: 'retrieve_done',
        citations_count: 3,
        elapsed_sec: 1.25,
      })
    ).toBe('检索完成：3 条引用（1.25s）')
  })

  it('formats route decisions with model and reason details', () => {
    expect(
      formatRouteStep({
        route: 'hybrid',
        model_used: 'gpt-test',
        reason: 'dataset requires broader recall',
      })
    ).toBe('模型路由：hybrid（gpt-test） - dataset requires broader recall')
  })

  it('only formats rewrite steps when the backend says rewrite was used', () => {
    expect(formatRewriteStep({ used: false, rewritten: 'noop' })).toBeNull()
    expect(formatRewriteStep({ used: true, rewritten: 'rewrite me', elapsed_sec: 0.52 })).toBe(
      '查询改写：rewrite me（0.52s）'
    )
  })

  it('renders structured output as fenced json when available', () => {
    expect(formatAssistantContent('plain', true, { answer: 42 })).toBe('```json\n{\n  "answer": 42\n}\n```')
    expect(formatAssistantContent('plain', false, { answer: 42 })).toBe('plain')
  })

  it('builds chat requests without leaking an empty rag config payload', () => {
    expect(
      buildChatRequest({
        conversationId: 'conv-1',
        message: 'hello',
        history: [{ role: 'user', content: 'prev' }],
        documentIds: ['doc-1'],
        promptTemplateId: 'tmpl-1',
        structuredOutput: true,
        structuredPreset: 'summary',
        enableLongTermMemory: true,
        enableSummaryMemory: false,
        ragConfig: {},
        useGraph: false,
      })
    ).toEqual({
      conversation_id: 'conv-1',
      message: 'hello',
      history: [{ role: 'user', content: 'prev' }],
      document_ids: ['doc-1'],
      prompt_template_id: 'tmpl-1',
      stream: true,
      structured_output: true,
      structured_preset: 'summary',
      enable_long_term_memory: true,
      enable_summary_memory: false,
    })
  })

  it('preserves explicit low-latency RAG expansion flags', () => {
    expect(
      buildChatRequest({
        message: 'WQW',
        history: [],
        ragConfig: {
          enable_multi_query: false,
          enable_hyde: false,
          retrieval_mode: 'hybrid',
          use_graph: false,
        },
        useGraph: false,
      }).rag_config
    ).toMatchObject({
      enable_multi_query: false,
      enable_hyde: false,
      retrieval_mode: 'hybrid',
      use_graph: false,
    })
  })
})
