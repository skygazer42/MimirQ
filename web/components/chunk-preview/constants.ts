/**
 * ChunkPreview 常量定义
 */

export const SEPARATOR_PRESET_OPTIONS: Array<{
  value:
    | 'paragraph'
    | 'line'
    | 'sentence_cn'
    | 'sentence_en'
    | 'markdown_hr'
    | 'markdown_h1'
    | 'markdown_h2'
    | 'custom'
  label: string
  hint: string
}> = [
  { value: 'paragraph', label: String.raw`段落（\\n\\n）`, hint: '按空行分段（推荐）' },
  { value: 'line', label: String.raw`按行（\\n）`, hint: '按换行切分' },
  { value: 'sentence_cn', label: '中文句号（。)', hint: '按中文句号切分' },
  { value: 'sentence_en', label: '英文句号（.)', hint: '按英文句号切分' },
  { value: 'markdown_hr', label: 'Markdown 分隔线（---）', hint: '适用于 slides/sections' },
  { value: 'markdown_h1', label: 'Markdown H1（# ）', hint: '按一级标题切分' },
  { value: 'markdown_h2', label: 'Markdown H2（## ）', hint: '按二级标题切分' },
  { value: 'custom', label: '自定义', hint: '输入自定义分隔符（支持转义）' },
]

// 示例文档
export const EXAMPLE_TEXT = `# 检索增强生成 (RAG) 简介

检索增强生成（Retrieval-Augmented Generation，简称 RAG）是一种赋予大型语言模型（LLM）从外部知识库检索相关信息能力的技术。

## 为什么需要 RAG？
虽然 LLM 拥有强大的通用知识，但在处理特定领域、私有数据或最新信息时往往力不从心。RAG 通过连接外部数据源，解决了以下问题：
1. **幻觉问题**：模型不再凭空捏造，而是基于检索到的事实生成回答。
2. **知识时效性**：无需重新训练模型即可更新知识库。
3. **数据隐私**：可以将敏感数据保存在本地知识库中，仅在生成时检索相关片段。

## RAG 的工作流程
1. **文档加载与切分**：将长文档切分为较小的文本块（Chunks）。
2. **向量化（Embedding）**：将文本块转化为向量存储在向量数据库中。
3. **检索（Retrieval）**：根据用户问题的向量，在数据库中查找最相似的文本块。
4. **生成（Generation）**：将检索到的上下文和用户问题一起发送给 LLM，生成最终回答。

通过合理的切片策略（Chunking Strategy），我们可以显著提升 RAG 系统的检索准确率和回答质量。`
