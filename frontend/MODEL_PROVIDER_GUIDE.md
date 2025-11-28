# 模型提供商配置指南

## 概述

MimirQ 现在支持类似 Dify 的模型提供商可视化配置界面,让你可以轻松管理多个主流 LLM 服务商的 API 配置。

## 功能特点

### ✨ 支持的模型提供商

我们支持以下 8 个主流 AI 模型提供商:

| 提供商 | 图标 | 描述 | 模型示例 |
|--------|------|------|---------|
| **OpenAI** | 🟢 | GPT-4, GPT-3.5 系列模型 | GPT-4 Turbo, GPT-3.5 Turbo, Embedding 3 |
| **Anthropic** | 🟠 | Claude 3 系列模型 | Claude 3 Opus, Sonnet, Haiku |
| **DeepSeek** | 🔵 | 高性价比的中文大模型 | DeepSeek Chat, DeepSeek Coder |
| **智谱 AI** | 🟣 | GLM-4 系列模型 | GLM-4, GLM-4 Air |
| **通义千问** | 🔷 | 阿里云大模型服务 | Qwen Turbo, Qwen Plus, Qwen Max |
| **Moonshot AI** | 🌙 | Kimi 长文本大模型 | Moonshot 8K/32K/128K |
| **Ollama** | ⚫ | 本地部署的开源模型 | Llama 2, Mistral, Qwen |
| **本地 Embedding** | 🟢 | BGE 中文向量模型 | BGE Large/Base ZH v1.5 |

## 使用方法

### 1. 访问设置页面

点击左侧导航栏的 **设置** 图标进入配置页面。

### 2. 选择提供商

在网格布局中找到你想要配置的提供商卡片,点击卡片或 "立即配置" 按钮。

### 3. 填写配置信息

在弹出的配置对话框中填写:

- **API Key** (必填): 从提供商官网获取
- **API Base URL** (可选): 默认已填写,支持自定义代理
- **高级设置** (可选):
  - Temperature: 控制输出随机性 (0-2)
  - Max Tokens: 最大输出 token 数
  - Timeout: 请求超时时间 (秒)

### 4. 测试连接

点击 "测试连接" 按钮验证 API Key 是否有效。

### 5. 保存配置

点击 "保存配置" 按钮完成设置。配置成功后,卡片右上角会显示 ✅ 标记。

## 官方文档链接

| 提供商 | 获取 API Key | API 文档 |
|--------|-------------|----------|
| OpenAI | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | [文档](https://platform.openai.com/docs) |
| Anthropic | [console.anthropic.com](https://console.anthropic.com/) | [文档](https://docs.anthropic.com) |
| DeepSeek | [platform.deepseek.com](https://platform.deepseek.com/) | [文档](https://platform.deepseek.com/docs) |
| 智谱 AI | [open.bigmodel.cn](https://open.bigmodel.cn/) | [文档](https://open.bigmodel.cn/dev/api) |
| 通义千问 | [dashscope.console.aliyun.com](https://dashscope.console.aliyuncs.com/) | [文档](https://help.aliyun.com/document_detail/2400395.html) |
| Moonshot | [platform.moonshot.cn](https://platform.moonshot.cn/) | [文档](https://platform.moonshot.cn/docs) |
| Ollama | [ollama.ai](https://ollama.ai/) | [文档](https://github.com/ollama/ollama) |

## 默认 API 端点

系统会自动为每个提供商填充默认的 API Base URL:

```typescript
openai:     https://api.openai.com/v1
anthropic:  https://api.anthropic.com
deepseek:   https://api.deepseek.com/v1
zhipu:      https://open.bigmodel.cn/api/paas/v4
qwen:       https://dashscope.aliyuncs.com/compatible-mode/v1
moonshot:   https://api.moonshot.cn/v1
ollama:     http://localhost:11434/v1
```

## 使用代理服务

如果你使用第三方代理服务 (如 OneAPI, New API 等),可以修改 API Base URL:

```
示例: https://api.your-proxy.com/v1
```

## 本地 Embedding

本地 Embedding 使用 BGE 模型,无需 API Key 即可使用:

- **模型**: BAAI/bge-large-zh-v1.5
- **设备**: CPU 或 CUDA (在后端 .env 中配置)
- **特点**: 免费、隐私保护、无网络依赖

## 界面截图

### 模型配置主页

![模型配置页面](./docs/images/model-providers.png)

展示所有可用的模型提供商,以卡片形式呈现,包含:
- 品牌图标 (官方 SVG)
- 提供商名称和描述
- 可用模型列表
- 配置状态指示器

### 配置对话框

![配置对话框](./docs/images/config-dialog.png)

包含:
- API Key 输入 (支持显示/隐藏)
- API Base URL 配置
- 高级参数设置 (Temperature, Max Tokens, Timeout)
- 连接测试功能
- 一键保存

## 技术实现

### 组件结构

```
components/
├── provider-icon.tsx           # 品牌图标组件 (SVG)
├── model-provider-card.tsx     # 提供商卡片
└── model-config-dialog.tsx     # 配置对话框

types/
└── models.ts                   # 模型类型定义和配置数据

app/
└── settings/
    └── page.tsx                # 设置页面
```

### 类型定义

```typescript
interface ModelProvider {
  id: string
  name: string
  description: string
  icon: string
  color: string
  isConfigured: boolean
  models: ModelConfig[]
  config?: ProviderConfig
}
```

## 常见问题

### Q: 配置多个提供商会冲突吗?
A: 不会,每个提供商的配置是独立的,你可以同时配置多个并在使用时选择。

### Q: API Key 会保存在哪里?
A: 当前存储在浏览器的状态中。后续版本会支持:
- LocalStorage 持久化
- 后端加密存储
- 环境变量配置

### Q: 如何切换使用不同的模型?
A: 在对话页面会有模型选择器,可以从已配置的提供商中选择具体模型。

### Q: Ollama 需要特殊配置吗?
A: 需要先在本地安装并启动 Ollama 服务:
```bash
# 安装 Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# 下载模型
ollama pull llama2

# 服务会自动运行在 http://localhost:11434
```

## 后续规划

- [ ] 配置持久化 (LocalStorage + 后端)
- [ ] 批量导入/导出配置
- [ ] 成本统计和配额管理
- [ ] 模型性能对比
- [ ] 支持更多提供商 (Gemini, Azure OpenAI 等)
- [ ] 自动检测可用模型列表

## 贡献指南

欢迎提交 PR 添加更多模型提供商! 请参考现有代码结构:

1. 在 `types/models.ts` 中添加提供商配置
2. 在 `components/provider-icon.tsx` 中添加官方图标
3. 测试配置流程是否正常

---

如有问题或建议,请在 GitHub Issues 中反馈。
