# MimirQ API 接口文档

> 本文档面向开发者，帮助你快速接入 MimirQ 知识库问答系统。

---

## 目录

1. [快速入门](#快速入门)
2. [核心使用流程](#核心使用流程)
3. [完整代码示例](#完整代码示例)
4. [API 详细参考](#api-详细参考)
5. [常见问题解答](#常见问题解答)

---

# 快速入门

## 这是什么？

MimirQ 是一个 **RAG（检索增强生成）知识库问答系统**。简单来说：

1. 你上传文档（PDF、Word、Markdown 等）
2. 系统自动解析、分块、向量化存储
3. 用户提问时，系统检索相关内容，结合 AI 生成答案

## 环境准备

### 基础信息

| 项目 | 值 |
|------|-----|
| Base URL | `http://localhost:8000/api/v1` |
| 数据格式 | JSON |
| 流式响应 | SSE (Server-Sent Events) |

### 你需要准备

1. **后端服务运行中** - 确保 MimirQ 后端已启动
2. **HTTP 客户端** - 如 Postman、curl、或你的代码
3. **认证信息** - 用户账号或 API Token

---

## 认证方式（二选一）

### 方式一：JWT Token（推荐）

先登录获取 token，然后在请求头中携带：

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 方式二：Header 模式（开发调试用）

直接在请求头中传入用户和租户信息：

```
X-User-ID: your-account-id
X-Tenant-ID: your-tenant-id
```

---

## 5 分钟快速体验

### 第 1 步：注册账号

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "username": "testuser",
    "password": "password123"
  }'
```

**返回示例：**
```json
{
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "test@example.com",
    "username": "testuser"
  },
  "token": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "expires_in": 3600
  }
}
```

> 保存 `access_token`，后续请求都需要用到！

### 第 2 步：上传文档

```bash
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/your/document.pdf"
```

**返回示例：**
```json
{
  "id": "doc-uuid-12345",
  "filename": "document.pdf",
  "status": "pending",
  "processing_progress": 0
}
```

> 文档会在后台自动处理，状态从 `pending` → `processing` → `completed`

### 第 3 步：检查文档状态

```bash
curl http://localhost:8000/api/v1/documents/doc-uuid-12345/status \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**返回示例：**
```json
{
  "id": "doc-uuid-12345",
  "status": "completed",
  "processing_progress": 100,
  "current_stage": "done"
}
```

### 第 4 步：开始对话！

```bash
curl -X POST http://localhost:8000/api/v1/chat/stream \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "这份文档主要讲了什么？",
    "document_ids": ["doc-uuid-12345"],
    "stream": true
  }'
```

**返回（SSE 流式）：**
```
data: {"type": "citations", "data": [...]}

data: {"type": "token", "data": {"content": "这份"}}

data: {"type": "token", "data": {"content": "文档"}}

data: {"type": "token", "data": {"content": "主要"}}

...

data: {"type": "done", "data": {"conversation_id": "conv-uuid", "total_tokens": 150}}
```

恭喜！你已经完成了基本的接入流程！

---

# 核心使用流程

## 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        你的应用程序                               │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     MimirQ API 网关                              │
│                  http://localhost:8000/api/v1                   │
└─────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│   文档管理     │      │   对话问答     │      │   知识图谱     │
│  /documents   │      │    /chat      │      │     /kg       │
└───────────────┘      └───────────────┘      └───────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                        存储层                                    │
│   PostgreSQL (元数据)  │  Milvus (向量)  │  MinIO (文件)         │
└─────────────────────────────────────────────────────────────────┘
```

## 典型使用场景

### 场景 1：构建企业知识库问答

```
用户 ──► 上传公司文档 ──► 系统处理 ──► 员工提问 ──► AI 回答 + 引用来源
```

**步骤：**
1. 创建数据集（可选，用于分类管理）
2. 批量上传文档
3. 等待处理完成
4. 调用对话接口

### 场景 2：文档智能分析

```
用户 ──► 上传报告 ──► 提取关键信息 ──► 生成摘要/FAQ
```

**步骤：**
1. 上传文档
2. 使用结构化输出功能
3. 获取 JSON 格式的分析结果

## 文档处理流程详解

```
上传文档                    后台自动处理                      可用于问答
   │                            │                              │
   ▼                            ▼                              ▼
┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐
│上传  │───►│解析  │───►│分块  │───►│向量化│───►│存储  │───►│完成  │
│文件  │    │PDF等 │    │切分  │    │Embed │    │Milvus│    │可用  │
└──────┘    └──────┘    └──────┘    └──────┘    └──────┘    └──────┘
   │
   ▼
状态: pending → processing → completed
```

### 支持的文件格式

| 格式 | 扩展名 | 说明 |
|------|--------|------|
| PDF | .pdf | 支持扫描件 OCR |
| Word | .docx, .doc | Office 文档 |
| Markdown | .md | 原生支持 |
| 文本 | .txt | 纯文本 |
| HTML | .html | 网页内容 |
| Excel | .xlsx, .xls | 表格数据 |

### 解析器选择

系统支持多种解析器，可根据文档类型选择：

| 解析器 | 适用场景 | 特点 |
|--------|---------|------|
| `auto` | 通用（默认） | 自动选择最佳解析器 |
| `basic` | 简单文档 | 速度快，内置 |
| `docling` | 复杂 PDF | IBM 开源，效果好 |
| `mineru` | 学术论文 | 支持公式、表格 |
| `marker` | 扫描件 | OCR 能力强 |

## 对话流程详解

```
用户提问                     RAG 检索                      AI 生成
   │                            │                            │
   ▼                            ▼                            ▼
┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐
│问题  │───►│向量化│───►│检索  │───►│重排序│───►│生成  │
│输入  │    │Query │    │Top-K │    │Rerank│    │答案  │
└──────┘    └──────┘    └──────┘    └──────┘    └──────┘
                                                    │
                                                    ▼
                                              返回答案 + 引用来源
```

### RAG 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `top_k` | 5 | 检索返回的文档块数量 |
| `score_threshold` | 0.7 | 相似度阈值，低于此值的结果会被过滤 |
| `retrieval_mode` | hybrid | 检索模式：vector/keyword/hybrid/mmr |
| `enable_reranker` | false | 是否启用重排序（提高精度） |

---

# 完整代码示例

## Python 示例

### 安装依赖

```bash
pip install requests sseclient-py
```

### 完整示例代码

```python
import requests
import json
from sseclient import SSEClient

class MimirQClient:
    """MimirQ API 客户端"""

    def __init__(self, base_url="http://localhost:8000/api/v1", token=None):
        self.base_url = base_url
        self.token = token
        self.headers = {"Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def login(self, email, password):
        """登录获取 token"""
        resp = requests.post(
            f"{self.base_url}/auth/login",
            json={"identifier": email, "password": password}
        )
        resp.raise_for_status()
        data = resp.json()
        self.token = data["token"]["access_token"]
        self.headers["Authorization"] = f"Bearer {self.token}"
        return data

    def upload_document(self, file_path, parser_backend="auto"):
        """上传文档"""
        with open(file_path, "rb") as f:
            files = {"file": f}
            data = {"parser_backend": parser_backend}
            resp = requests.post(
                f"{self.base_url}/documents/upload",
                headers={"Authorization": self.headers.get("Authorization")},
                files=files,
                data=data
            )
        resp.raise_for_status()
        return resp.json()

    def get_document_status(self, document_id):
        """获取文档处理状态"""
        resp = requests.get(
            f"{self.base_url}/documents/{document_id}/status",
            headers=self.headers
        )
        resp.raise_for_status()
        return resp.json()

    def chat_stream(self, message, document_ids, conversation_id=None):
        """流式对话（生成器）"""
        payload = {
            "message": message,
            "document_ids": document_ids,
            "stream": True
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        resp = requests.post(
            f"{self.base_url}/chat/stream",
            headers=self.headers,
            json=payload,
            stream=True
        )
        resp.raise_for_status()

        client = SSEClient(resp)
        for event in client.events():
            if event.data:
                yield json.loads(event.data)


# 使用示例
if __name__ == "__main__":
    # 1. 初始化客户端
    client = MimirQClient()

    # 2. 登录
    client.login("test@example.com", "password123")
    print("登录成功！")

    # 3. 上传文档
    doc = client.upload_document("./my_document.pdf")
    doc_id = doc["id"]
    print(f"文档已上传，ID: {doc_id}")

    # 4. 等待处理完成
    import time
    while True:
        status = client.get_document_status(doc_id)
        print(f"处理状态: {status['status']} ({status['processing_progress']}%)")
        if status["status"] == "completed":
            break
        time.sleep(2)

    # 5. 开始对话
    print("\n开始对话...")
    for event in client.chat_stream("这份文档讲了什么？", [doc_id]):
        if event["type"] == "token":
            print(event["data"]["content"], end="", flush=True)
        elif event["type"] == "done":
            print("\n\n对话完成！")
```

## JavaScript/TypeScript 示例

### 前端（浏览器/React/Vue）

```javascript
class MimirQClient {
  constructor(baseUrl = 'http://localhost:8000/api/v1') {
    this.baseUrl = baseUrl;
    this.token = null;
  }

  // 设置 Token
  setToken(token) {
    this.token = token;
  }

  // 通用请求方法
  async request(path, options = {}) {
    const headers = {
      'Content-Type': 'application/json',
      ...(this.token && { Authorization: `Bearer ${this.token}` }),
      ...options.headers,
    };

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    }

    return response.json();
  }

  // 登录
  async login(email, password) {
    const data = await this.request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ identifier: email, password }),
    });
    this.token = data.token.access_token;
    return data;
  }

  // 上传文档
  async uploadDocument(file) {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${this.baseUrl}/documents/upload`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.token}` },
      body: formData,
    });

    return response.json();
  }

  // 流式对话
  async *chatStream(message, documentIds, conversationId = null) {
    const body = {
      message,
      document_ids: documentIds,
      stream: true,
      ...(conversationId && { conversation_id: conversationId }),
    };

    const response = await fetch(`${this.baseUrl}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.token}`,
      },
      body: JSON.stringify(body),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6));
          yield data;
        }
      }
    }
  }
}

// 使用示例
const client = new MimirQClient();

// 登录
await client.login('test@example.com', 'password123');

// 流式对话
for await (const event of client.chatStream('你好', ['doc-id'])) {
  if (event.type === 'token') {
    console.log(event.data.content); // 逐字输出
  }
}
```

### React Hook 示例

```jsx
import { useState, useCallback } from 'react';

function useMimirQChat(token, documentIds) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);

  const sendMessage = useCallback(async (text) => {
    setLoading(true);
    setMessages(prev => [...prev, { role: 'user', content: text }]);

    let assistantMessage = '';

    try {
      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: text,
          document_ids: documentIds,
          stream: true,
        }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'token') {
              assistantMessage += event.data.content;
              setMessages(prev => {
                const newMessages = [...prev];
                const lastIdx = newMessages.length - 1;
                if (newMessages[lastIdx]?.role === 'assistant') {
                  newMessages[lastIdx].content = assistantMessage;
                } else {
                  newMessages.push({ role: 'assistant', content: assistantMessage });
                }
                return newMessages;
              });
            }
          }
        }
      }
    } finally {
      setLoading(false);
    }
  }, [token, documentIds]);

  return { messages, sendMessage, loading };
}
```

## cURL 命令速查

### 认证相关

```bash
# 注册
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","username":"user","password":"pass123"}'

# 登录
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"identifier":"user@example.com","password":"pass123"}'
```

### 文档相关

```bash
# 上传文档
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@document.pdf" \
  -F "parser_backend=auto"

# 查看文档列表
curl http://localhost:8000/api/v1/documents/ \
  -H "Authorization: Bearer YOUR_TOKEN"

# 查看文档状态
curl http://localhost:8000/api/v1/documents/DOC_ID/status \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 对话相关

```bash
# 流式对话
curl -X POST http://localhost:8000/api/v1/chat/stream \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "这份文档讲了什么？",
    "document_ids": ["DOC_ID"],
    "stream": true
  }'

# 获取对话历史
curl http://localhost:8000/api/v1/chat/conversations/CONV_ID/messages \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

# API 详细参考

## 通用说明

### 请求头

| 头部 | 必填 | 说明 |
|------|------|------|
| `Authorization` | 是* | `Bearer <token>` 格式 |
| `X-User-ID` | 是* | Header 模式下的用户 ID |
| `X-Tenant-ID` | 是* | Header 模式下的租户 ID |
| `Content-Type` | 是 | `application/json` 或 `multipart/form-data` |

> *认证方式二选一

### 分页参数

所有列表接口支持：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `skip` | int | 0 | 跳过记录数 |
| `limit` | int | 20 | 返回记录数（最大 100） |

### 响应格式

**成功响应：**
```json
{
  "total": 100,
  "items": [...]
}
```

**错误响应：**
```json
{
  "detail": "错误描述信息"
}
```

### HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 204 | 删除成功（无返回内容） |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |
| 502 | 上游服务错误（如 LLM 调用失败） |
| 503 | 服务不可用 |

---

## 1. 认证 API `/auth`

### POST /auth/register - 用户注册

**请求体：**
```json
{
  "email": "user@example.com",
  "username": "myuser",
  "password": "password123"
}
```

**响应 (201)：**
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "username": "myuser"
  },
  "token": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "expires_in": 3600
  }
}
```

### POST /auth/login - 用户登录

**请求体：**
```json
{
  "identifier": "user@example.com",
  "password": "password123"
}
```

> `identifier` 可以是邮箱或用户名

### GET /auth/me - 获取当前用户

**响应 (200)：**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "username": "myuser"
}
```

---

## 2. 对话 API `/chat`

### POST /chat/stream - 流式对话（核心接口）

**请求体：**
```json
{
  "message": "你的问题",
  "document_ids": ["doc-uuid-1", "doc-uuid-2"],
  "conversation_id": "可选，不传则创建新对话",
  "stream": true,
  "history": [
    {"role": "user", "content": "之前的问题"},
    {"role": "assistant", "content": "之前的回答"}
  ],
  "rag_config": {
    "top_k": 5,
    "score_threshold": 0.7,
    "retrieval_mode": "hybrid"
  }
}
```

**SSE 响应事件：**

| 事件类型 | 说明 | 数据示例 |
|----------|------|----------|
| `citations` | 引用来源 | `{"data": [{"document_name": "...", "chunk_content": "..."}]}` |
| `token` | 回答片段 | `{"data": {"content": "这是"}}` |
| `done` | 完成信号 | `{"data": {"conversation_id": "uuid", "total_tokens": 150}}` |
| `error` | 错误信息 | `{"data": {"message": "错误描述"}}` |

### POST /chat/conversations - 创建对话

**请求体：**
```json
{
  "title": "对话标题",
  "document_ids": ["doc-uuid-1"]
}
```

### GET /chat/conversations - 获取对话列表

**查询参数：** `skip`, `limit`

### GET /chat/conversations/{id}/messages - 获取消息历史

### DELETE /chat/conversations/{id} - 删除对话

---

## 3. 文档管理 API `/documents`

### POST /documents/upload - 上传文档

**Content-Type:** `multipart/form-data`

**表单参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | 是 | 文档文件 |
| parser_backend | string | 否 | 解析器：auto/basic/docling/mineru |
| chunk_strategy | string | 否 | 分块策略 |
| dataset_id | UUID | 否 | 所属数据集 |
| chunk_size | int | 否 | 分块大小（默认 1000） |
| chunk_overlap | int | 否 | 重叠大小（默认 200） |

**响应 (201)：**
```json
{
  "id": "doc-uuid",
  "filename": "document.pdf",
  "status": "pending",
  "processing_progress": 0
}
```

### GET /documents/{id}/status - 获取处理状态

**响应：**
```json
{
  "id": "doc-uuid",
  "status": "processing",
  "processing_progress": 50,
  "current_stage": "chunking"
}
```

**状态值：** `pending` → `processing` → `completed` / `failed`

### GET /documents/ - 获取文档列表

### GET /documents/{id} - 获取文档详情

### DELETE /documents/{id} - 删除文档

---

## 4. 数据集 API `/datasets`

### POST /datasets/ - 创建数据集

```json
{
  "name": "产品文档",
  "description": "产品相关文档集合"
}
```

### GET /datasets/ - 获取数据集列表

### GET /datasets/{id} - 获取数据集详情

### PATCH /datasets/{id} - 更新数据集

### DELETE /datasets/{id} - 删除数据集

---

## 5. 健康检查 API `/health`

### GET /health - 轻量检查

```json
{"ok": true, "time": "2024-01-01T00:00:00Z"}
```

### GET /health/ready - 就绪探针

检查数据库、Milvus、Redis 连接状态。

---

# 常见问题解答

## Q1: 如何处理 SSE 流式响应？

SSE（Server-Sent Events）是一种服务器推送技术。每行数据格式为：

```
data: {"type": "token", "data": {"content": "内容"}}
```

**处理步骤：**
1. 按行分割响应
2. 去掉 `data: ` 前缀
3. JSON 解析
4. 根据 `type` 字段处理

## Q2: 文档上传后多久可以使用？

取决于文档大小和解析器：
- 小文档（< 1MB）：通常 10-30 秒
- 中等文档（1-10MB）：1-5 分钟
- 大文档（> 10MB）：可能需要更长时间

**建议：** 轮询 `/documents/{id}/status` 接口检查状态。

## Q3: 如何提高回答质量？

1. **调整 top_k**：增加检索数量（5→10）
2. **启用重排序**：`enable_reranker: true`
3. **调整阈值**：降低 `score_threshold`（0.7→0.5）
4. **优化文档**：确保文档质量，避免扫描件

## Q4: Token 过期怎么办？

Token 默认 1 小时过期。解决方案：
1. 重新调用登录接口获取新 Token
2. 在前端实现 Token 刷新逻辑

## Q5: 如何调试检索效果？

使用 RAG 调试接口：

```bash
POST /api/v1/rag/retrieve-preview
```

可以查看检索到的文档块和相似度分数。

## Q6: 支持哪些语言？

系统支持中文和英文，底层 LLM 决定了语言能力。

---

# 附录

## API 路径速查表

| 功能 | 方法 | 路径 |
|------|------|------|
| 注册 | POST | /auth/register |
| 登录 | POST | /auth/login |
| 上传文档 | POST | /documents/upload |
| 文档状态 | GET | /documents/{id}/status |
| 流式对话 | POST | /chat/stream |
| 对话列表 | GET | /chat/conversations |
| 健康检查 | GET | /health |

## 联系与支持

如有问题，请联系开发团队或查看项目文档。

---

*文档版本：1.0 | 最后更新：2024*
