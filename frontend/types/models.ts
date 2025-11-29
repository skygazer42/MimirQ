/**
 * 模型提供商类型定义
 */

export type ProviderCategory = 'model' | 'embedding' | 'reranker'

export interface ModelProvider {
  id: string
  name: string
  description: string
  icon: string // emoji or icon component name
  color: string // Tailwind color class
  category: ProviderCategory // 分类：模型/向量/重排序
  isConfigured: boolean
  models: ModelConfig[]
  config?: ProviderConfig
}

export interface ModelConfig {
  id: string
  name: string
  displayName: string
  type: 'chat' | 'embedding' | 'reranker' | 'image' | 'audio'
  contextWindow?: number
  maxTokens?: number
  pricing?: {
    input: number // per 1M tokens
    output: number
  }
}

export interface ProviderConfig {
  apiKey?: string
  apiBase?: string
  organizationId?: string
  projectId?: string
  temperature?: number
  maxTokens?: number
  timeout?: number
}

export const MODEL_PROVIDERS: ModelProvider[] = [
  // ==================== 语言模型 ====================
  {
    id: 'openai',
    name: 'OpenAI',
    description: 'GPT-4, GPT-3.5 系列模型',
    icon: 'openai',
    color: 'emerald',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'gpt-4-turbo-preview',
        name: 'gpt-4-turbo-preview',
        displayName: 'GPT-4 Turbo',
        type: 'chat',
        contextWindow: 128000,
        maxTokens: 4096,
        pricing: { input: 10, output: 30 }
      },
      {
        id: 'gpt-4',
        name: 'gpt-4',
        displayName: 'GPT-4',
        type: 'chat',
        contextWindow: 8192,
        pricing: { input: 30, output: 60 }
      },
      {
        id: 'gpt-3.5-turbo',
        name: 'gpt-3.5-turbo',
        displayName: 'GPT-3.5 Turbo',
        type: 'chat',
        contextWindow: 16385,
        pricing: { input: 0.5, output: 1.5 }
      }
    ]
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    description: 'Claude 3 系列模型',
    icon: 'anthropic',
    color: 'orange',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'claude-3-opus',
        name: 'claude-3-opus-20240229',
        displayName: 'Claude 3 Opus',
        type: 'chat',
        contextWindow: 200000,
        pricing: { input: 15, output: 75 }
      },
      {
        id: 'claude-3-sonnet',
        name: 'claude-3-sonnet-20240229',
        displayName: 'Claude 3 Sonnet',
        type: 'chat',
        contextWindow: 200000,
        pricing: { input: 3, output: 15 }
      },
      {
        id: 'claude-3-haiku',
        name: 'claude-3-haiku-20240307',
        displayName: 'Claude 3 Haiku',
        type: 'chat',
        contextWindow: 200000,
        pricing: { input: 0.25, output: 1.25 }
      }
    ]
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    description: '高性价比的中文大模型',
    icon: 'deepseek',
    color: 'blue',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'deepseek-chat',
        name: 'deepseek-chat',
        displayName: 'DeepSeek Chat',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 1, output: 2 }
      },
      {
        id: 'deepseek-coder',
        name: 'deepseek-coder',
        displayName: 'DeepSeek Coder',
        type: 'chat',
        contextWindow: 16384,
        pricing: { input: 1, output: 2 }
      }
    ]
  },
  {
    id: 'zhipu',
    name: '智谱 AI',
    description: 'GLM-4 系列模型',
    icon: 'zhipu',
    color: 'purple',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'glm-4',
        name: 'glm-4',
        displayName: 'GLM-4',
        type: 'chat',
        contextWindow: 128000,
        pricing: { input: 10, output: 10 }
      },
      {
        id: 'glm-4-air',
        name: 'glm-4-air',
        displayName: 'GLM-4 Air',
        type: 'chat',
        contextWindow: 128000,
        pricing: { input: 1, output: 1 }
      }
    ]
  },
  {
    id: 'qwen',
    name: '通义千问',
    description: '阿里云大模型服务',
    icon: 'qwen',
    color: 'sky',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'qwen-turbo',
        name: 'qwen-turbo',
        displayName: 'Qwen Turbo',
        type: 'chat',
        contextWindow: 8192,
        pricing: { input: 2, output: 6 }
      },
      {
        id: 'qwen-plus',
        name: 'qwen-plus',
        displayName: 'Qwen Plus',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 4, output: 12 }
      },
      {
        id: 'qwen-max',
        name: 'qwen-max',
        displayName: 'Qwen Max',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 40, output: 120 }
      }
    ]
  },
  {
    id: 'moonshot',
    name: 'Moonshot AI',
    description: 'Kimi 长文本大模型',
    icon: 'moonshot',
    color: 'indigo',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'moonshot-v1-8k',
        name: 'moonshot-v1-8k',
        displayName: 'Moonshot 8K',
        type: 'chat',
        contextWindow: 8192,
        pricing: { input: 12, output: 12 }
      },
      {
        id: 'moonshot-v1-32k',
        name: 'moonshot-v1-32k',
        displayName: 'Moonshot 32K',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 24, output: 24 }
      },
      {
        id: 'moonshot-v1-128k',
        name: 'moonshot-v1-128k',
        displayName: 'Moonshot 128K',
        type: 'chat',
        contextWindow: 131072,
        pricing: { input: 60, output: 60 }
      }
    ]
  },
  {
    id: 'ollama',
    name: 'Ollama',
    description: '本地部署的开源模型',
    icon: 'ollama',
    color: 'gray',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'llama2',
        name: 'llama2',
        displayName: 'Llama 2',
        type: 'chat',
        contextWindow: 4096
      },
      {
        id: 'mistral',
        name: 'mistral',
        displayName: 'Mistral',
        type: 'chat',
        contextWindow: 8192
      },
      {
        id: 'qwen',
        name: 'qwen:14b',
        displayName: 'Qwen 14B',
        type: 'chat',
        contextWindow: 8192
      }
    ]
  },
  {
    id: 'ark',
    name: '火山引擎',
    description: '字节跳动云端大模型服务',
    icon: 'ark',
    color: 'orange',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'doubao-pro',
        name: 'doubao-pro-32k',
        displayName: 'Doubao Pro 32K',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 0.8, output: 2 }
      },
      {
        id: 'doubao-lite',
        name: 'doubao-lite-32k',
        displayName: 'Doubao Lite 32K',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 0.3, output: 0.6 }
      }
    ]
  },
  {
    id: 'lingyiwanwu',
    name: '零一万物',
    description: 'Yi 系列大模型',
    icon: 'lingyiwanwu',
    color: 'blue',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'yi-large',
        name: 'yi-large',
        displayName: 'Yi Large',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 20, output: 20 }
      },
      {
        id: 'yi-medium',
        name: 'yi-medium',
        displayName: 'Yi Medium',
        type: 'chat',
        contextWindow: 16384,
        pricing: { input: 2.5, output: 2.5 }
      }
    ]
  },
  {
    id: 'qianfan',
    name: '百度千帆',
    description: '文心一言系列模型',
    icon: 'qianfan',
    color: 'blue',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'ernie-4.0',
        name: 'ernie-4.0-8k',
        displayName: 'ERNIE 4.0',
        type: 'chat',
        contextWindow: 8192,
        pricing: { input: 30, output: 60 }
      },
      {
        id: 'ernie-3.5',
        name: 'ernie-3.5-8k',
        displayName: 'ERNIE 3.5',
        type: 'chat',
        contextWindow: 8192,
        pricing: { input: 4, output: 8 }
      }
    ]
  },
  {
    id: 'siliconflow',
    name: 'SiliconFlow',
    description: '高性价比模型聚合平台',
    icon: 'siliconflow',
    color: 'purple',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'qwen2.5-72b',
        name: 'Qwen/Qwen2.5-72B-Instruct',
        displayName: 'Qwen2.5 72B',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 4, output: 4 }
      },
      {
        id: 'deepseek-v2.5',
        name: 'deepseek-ai/DeepSeek-V2.5',
        displayName: 'DeepSeek V2.5',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 1.33, output: 1.33 }
      }
    ]
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    description: '多模型统一接入网关',
    icon: 'openrouter',
    color: 'indigo',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'auto',
        name: 'openrouter/auto',
        displayName: 'Auto (智能选择)',
        type: 'chat',
        contextWindow: 128000
      },
      {
        id: 'claude-3.5-sonnet',
        name: 'anthropic/claude-3.5-sonnet',
        displayName: 'Claude 3.5 Sonnet',
        type: 'chat',
        contextWindow: 200000
      }
    ]
  },
  {
    id: 'together',
    name: 'Together AI',
    description: '开源模型云端推理',
    icon: 'together',
    color: 'sky',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'llama-3.1-70b',
        name: 'meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo',
        displayName: 'Llama 3.1 70B',
        type: 'chat',
        contextWindow: 131072,
        pricing: { input: 0.88, output: 0.88 }
      },
      {
        id: 'mixtral-8x7b',
        name: 'mistralai/Mixtral-8x7B-Instruct-v0.1',
        displayName: 'Mixtral 8x7B',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 0.6, output: 0.6 }
      }
    ]
  },

  // ==================== Embedding 向量模型 ====================
  {
    id: 'openai-embedding',
    name: 'OpenAI Embedding',
    description: 'OpenAI 文本向量模型',
    icon: 'openai',
    color: 'emerald',
    category: 'embedding',
    isConfigured: false,
    models: [
      {
        id: 'text-embedding-3-large',
        name: 'text-embedding-3-large',
        displayName: 'Embedding 3 Large',
        type: 'embedding',
        contextWindow: 8191,
        pricing: { input: 0.13, output: 0 }
      },
      {
        id: 'text-embedding-3-small',
        name: 'text-embedding-3-small',
        displayName: 'Embedding 3 Small',
        type: 'embedding',
        contextWindow: 8191,
        pricing: { input: 0.02, output: 0 }
      }
    ]
  },
  {
    id: 'local-embedding',
    name: '本地 Embedding',
    description: 'BGE 中文向量模型',
    icon: 'local-embedding',
    color: 'green',
    category: 'embedding',
    isConfigured: true,
    models: [
      {
        id: 'bge-large-zh-v1.5',
        name: 'BAAI/bge-large-zh-v1.5',
        displayName: 'BGE Large ZH v1.5',
        type: 'embedding',
        contextWindow: 512
      },
      {
        id: 'bge-base-zh-v1.5',
        name: 'BAAI/bge-base-zh-v1.5',
        displayName: 'BGE Base ZH v1.5',
        type: 'embedding',
        contextWindow: 512
      },
      {
        id: 'bge-m3',
        name: 'BAAI/bge-m3',
        displayName: 'BGE M3 (多语言)',
        type: 'embedding',
        contextWindow: 8192
      }
    ]
  },

  // ==================== Reranker 重排序模型 ====================
  {
    id: 'local-reranker',
    name: '本地 Reranker',
    description: 'BGE 重排序模型',
    icon: 'reranker',
    color: 'amber',
    category: 'reranker',
    isConfigured: true,
    models: [
      {
        id: 'bge-reranker-v2-m3',
        name: 'BAAI/bge-reranker-v2-m3',
        displayName: 'BGE Reranker v2 M3',
        type: 'reranker',
        contextWindow: 8192
      },
      {
        id: 'bge-reranker-large',
        name: 'BAAI/bge-reranker-large',
        displayName: 'BGE Reranker Large',
        type: 'reranker',
        contextWindow: 512
      },
      {
        id: 'bge-reranker-base',
        name: 'BAAI/bge-reranker-base',
        displayName: 'BGE Reranker Base',
        type: 'reranker',
        contextWindow: 512
      }
    ]
  },
  {
    id: 'cohere-reranker',
    name: 'Cohere Reranker',
    description: 'Cohere 云端重排序服务',
    icon: 'reranker',
    color: 'rose',
    category: 'reranker',
    isConfigured: false,
    models: [
      {
        id: 'rerank-english-v3.0',
        name: 'rerank-english-v3.0',
        displayName: 'Rerank English v3',
        type: 'reranker'
      },
      {
        id: 'rerank-multilingual-v3.0',
        name: 'rerank-multilingual-v3.0',
        displayName: 'Rerank Multilingual v3',
        type: 'reranker'
      }
    ]
  },
  {
    id: 'jina-reranker',
    name: 'Jina Reranker',
    description: 'Jina AI 重排序模型',
    icon: 'reranker',
    color: 'orange',
    category: 'reranker',
    isConfigured: false,
    models: [
      {
        id: 'jina-reranker-v2-base-multilingual',
        name: 'jina-reranker-v2-base-multilingual',
        displayName: 'Jina Reranker v2 多语言',
        type: 'reranker'
      }
    ]
  }
]
