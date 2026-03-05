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

### GET /documents/{id}/chunks - 获取文档切片列表（分页）

**查询参数：** `skip`, `limit`, `q`

### GET /documents/{id}/chunks/matches - 文档内查找（轻量）

**查询参数：** `q`, `limit`

### GET /documents/{id}/chunks/{chunk_id} - 获取单个切片

### GET /documents/{id}/parsed-content - 获取已持久化的解析文本（用于“文本定位/高亮”）

说明：此接口仅在 ingestion pipeline 开启 `persist_parsed_content` 时可用；未开启时返回 `available=false`（内容为空）。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| max_chars | int | 否 | 额外的返回长度上限（默认 200000；0 表示不额外截断） |

**响应 (200)：**
```json
{
  "document_id": "doc-uuid",
  "available": true,
  "markdown_content": "…清洗后 Markdown（可能截断）…",
  "original_markdown_content": "…原始解析 Markdown（可能截断）…",
  "persisted_meta": {
    "enabled": true,
    "max_chars": 200000,
    "original": { "raw_len": 123456, "stored_len": 200012, "truncated": true },
    "cleaned": { "raw_len": 120000, "stored_len": 120000, "truncated": false }
  },
  "markdown_truncated": false,
  "original_markdown_truncated": false,
  "max_chars": 200000
}
```

### DELETE /documents/{id} - 删除文档

---

## 4. 数据集 API `/datasets`

### POST /datasets/ - 创建数据集

```json
{
  "name": "产品文档",
  "description": "产品相关文档集合",
  "permission": "partial_members",
  "partial_member_list": ["alice", "bob"],
  "partial_group_list": ["11111111-1111-1111-1111-111111111111"]
}
```

说明：
- `permission` 支持：`all_team_members`（默认）/ `only_me` / `partial_members`
- 当 `permission=partial_members` 时，支持同时配置：
  - `partial_member_list`（成员 allowlist）
  - `partial_group_list`（组 allowlist，UUID；tenant-scoped）
- 详见：`docs/guides/dataset_permissions.md`

### GET /datasets/ - 获取数据集列表

### GET /datasets/{id} - 获取数据集详情

### PATCH /datasets/{id} - 更新数据集

示例（更新 allowlist）：

```json
{
  "permission": "partial_members",
  "partial_member_list": ["alice"],
  "partial_group_list": ["11111111-1111-1111-1111-111111111111"]
}
```

### DELETE /datasets/{id} - 删除数据集

---

## 5. 健康检查 API `/health`

### GET /health - 轻量检查

```json
{"ok": true, "time": "2024-01-01T00:00:00Z"}
```

### GET /health/ready - 就绪探针

检查数据库、Milvus、Redis、MinIO 连接状态。

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

---

# 错误码详解

## 错误响应格式

所有错误都返回统一格式：

```json
{
  "detail": "错误描述信息"
}
```

## 常见错误及解决方案

### 401 Unauthorized - 未认证

**错误信息：** `Not authenticated` 或 `Invalid token`

**原因：**
- 未携带 Token
- Token 已过期
- Token 格式错误

**解决方案：**
```python
# 检查请求头格式
headers = {
    "Authorization": "Bearer eyJhbGci..."  # 注意 Bearer 后有空格
}

# Token 过期时重新登录
if response.status_code == 401:
    new_token = client.login(email, password)
```

### 403 Forbidden - 权限不足

**错误信息：** `No permission to access this resource`

**原因：**
- 尝试访问其他租户的资源
- 用户角色权限不足

**解决方案：**
- 确认 document_id 属于当前用户
- 联系管理员提升权限

### 404 Not Found - 资源不存在

**错误信息：** `Document not found` 或 `Conversation not found`

**原因：**
- ID 错误或资源已删除
- 资源属于其他租户

**解决方案：**
```python
# 先检查资源是否存在
try:
    doc = client.get_document(doc_id)
except Exception as e:
    if "404" in str(e):
        print("文档不存在，请检查 ID")
```

### 400 Bad Request - 请求参数错误

**常见错误信息：**
- `document_ids are required`
- `Invalid UUID format`
- `message is required`

**解决方案：**
```python
# 确保必填参数存在
payload = {
    "message": "问题内容",      # 必填
    "document_ids": ["uuid"],   # 必填
    "stream": True
}
```

### 502 Bad Gateway - 上游服务错误

**错误信息：** `LLM call failed` 或 `Embedding service error`

**原因：**
- LLM API 调用失败
- API Key 无效或额度用尽

**解决方案：**
- 检查 LLM_API_KEY 配置
- 确认 API 服务可用

### 503 Service Unavailable - 服务不可用

**错误信息：** `KG is disabled` 或 `Feature not enabled`

**原因：** 功能未启用

**解决方案：** 在 `.env` 中启用对应功能

---

# RAG 配置参数详解

对话接口的 `rag_config` 参数控制检索行为，合理配置可显著提升回答质量。

## 基础参数

| 参数 | 类型 | 默认值 | 范围 | 说明 |
|------|------|--------|------|------|
| `top_k` | int | 5 | 1-50 | 检索返回的文档块数量 |
| `score_threshold` | float | 0.7 | 0-1 | 相似度阈值，低于此值被过滤 |
| `max_tokens` | int | 2000 | - | 上下文最大 token 数 |

**调优建议：**
```json
// 精确匹配场景（如FAQ）
{"top_k": 3, "score_threshold": 0.8}

// 广泛搜索场景（如研究）
{"top_k": 10, "score_threshold": 0.5}
```

## 检索模式 retrieval_mode

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `vector` | 纯向量检索 | 语义相似匹配 |
| `keyword` | 纯关键词检索 | 精确术语匹配 |
| `hybrid` | 混合检索（推荐） | 通用场景 |
| `mmr` | 最大边际相关性 | 需要多样性结果 |
| `auto` | 自动选择 | 不确定时使用 |

**混合检索权重：**
```json
{
  "retrieval_mode": "hybrid",
  "alpha": 0.6,           // 向量权重（0-1）
  "vector_weight": 0.6,   // 向量分数权重
  "keyword_weight": 0.4   // 关键词分数权重
}
```

## 重排序 Reranker

重排序可提高检索精度，但会增加延迟。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable_reranker` | bool | false | 是否启用 |
| `reranker_provider` | string | "llm" | 提供者：llm/pc/none |
| `reranker_top_n` | int | 20 | 重排序候选数量 |

**使用示例：**
```json
{
  "enable_reranker": true,
  "reranker_provider": "llm",
  "reranker_top_n": 15
}
```

---

# Postman 使用指南

## 导入配置

### 1. 创建环境变量

在 Postman 中创建环境，添加以下变量：

| 变量名 | 值 | 说明 |
|--------|-----|------|
| `base_url` | `http://localhost:8000/api/v1` | API 地址 |
| `token` | （登录后填入） | JWT Token |

### 2. 设置请求头

在 Collection 级别设置通用请求头：

```
Authorization: Bearer {{token}}
Content-Type: application/json
```

### 3. 自动保存 Token

在登录请求的 **Tests** 标签中添加脚本：

```javascript
if (pm.response.code === 200) {
    var jsonData = pm.response.json();
    pm.environment.set("token", jsonData.token.access_token);
    console.log("Token 已自动保存");
}
```

## 测试流式响应

Postman 对 SSE 支持有限，建议：

1. 使用 **curl** 测试流式接口
2. 或在 Postman 中将 `stream` 设为 `false`

```json
{
  "message": "测试问题",
  "document_ids": ["{{doc_id}}"],
  "stream": false
}
```

---

# 实战场景示例

## 场景1：企业客服机器人

**需求：** 基于产品手册回答用户问题

```python
# 1. 上传产品手册
doc = client.upload_document("产品手册.pdf")

# 2. 等待处理
wait_for_completion(doc["id"])

# 3. 配置高精度检索
rag_config = {
    "top_k": 5,
    "score_threshold": 0.75,
    "retrieval_mode": "hybrid",
    "enable_reranker": True
}

# 4. 回答用户问题
for event in client.chat_stream(
    "如何重置密码？",
    document_ids=[doc["id"]],
    rag_config=rag_config
):
    if event["type"] == "token":
        print(event["data"]["content"], end="")
```

## 场景2：文档摘要生成

**需求：** 自动生成文档摘要

```python
# 使用结构化输出
response = client.chat(
    message="请总结这份文档的要点",
    document_ids=[doc_id],
    structured_output=True,
    structured_preset="summary"
)
```

## 场景3：多文档对比分析

**需求：** 对比多份报告的差异

```python
# 上传多份文档
doc_ids = [
    client.upload_document("报告2023.pdf")["id"],
    client.upload_document("报告2024.pdf")["id"]
]

# 对比分析
client.chat_stream(
    "对比这两份报告的主要变化",
    document_ids=doc_ids,
    rag_config={"top_k": 10}
)
```

---

# 调试与排错指南

## 检索效果调试

使用 RAG 调试接口查看检索结果：

```bash
POST /api/v1/rag/retrieve-preview
```

```json
{
  "query": "你的问题",
  "document_ids": ["doc-id"],
  "rag_config": {"top_k": 10}
}
```

**返回内容包含：**
- 检索到的文档块
- 每个块的相似度分数
- 向量分数和关键词分数

## 常见问题排查

### 问题：回答不准确

**排查步骤：**
1. 检查检索结果是否相关
2. 调整 `top_k` 和 `score_threshold`
3. 启用重排序

### 问题：文档处理卡住

**排查步骤：**
1. 检查文档格式是否支持
2. 查看后端日志
3. 尝试更换解析器

### 问题：响应速度慢

**优化建议：**
1. 减少 `top_k` 值
2. 关闭重排序
3. 检查网络延迟

## 健康检查

```bash
# 快速检查
curl http://localhost:8000/api/v1/health

# 详细状态
curl http://localhost:8000/api/v1/health/ready
```

## 日志查看

后端日志位置：
- 控制台输出
- `logs/` 目录（如配置）

**关键日志关键词：**
- `ERROR` - 错误信息
- `retrieval` - 检索相关
- `LLM` - 模型调用

---

*文档版本：2.0 | 最后更新：2024*

---

# 高级功能：知识图谱

> 需要启用 `KG_ENABLED=true`

## 什么是知识图谱？

知识图谱从文档中自动提取：
- **实体**：人物、组织、地点、概念等
- **事件**：实体之间的关系和行为
- **关联**：实体间的连接关系

```
文档 ──► 抽取 ──► 实体+事件 ──► 图谱可视化
```

## 核心接口

### 获取图谱数据

```bash
GET /api/v1/kg/graph?document_ids=uuid1&document_ids=uuid2
```

**参数：**
| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_events | 200 | 最大事件数 |
| max_entities | 400 | 最大实体数 |
| max_links | 2000 | 最大连接数 |

**响应示例：**
```json
{
  "nodes": [
    {"id": "uuid", "label": "张三", "group": 1, "meta": {"kind": "entity", "type": "PERSON"}}
  ],
  "links": [
    {"source": "event-id", "target": "entity-id", "label": "参与"}
  ],
  "stats": {"events": 100, "entities": 200, "links": 500}
}
```

### 触发 KG 抽取

```bash
POST /api/v1/kg/documents/{document_id}/extract
```

### 搜索节点

```bash
GET /api/v1/kg/graph/search?q=关键词&limit=20
```

---

# 前端集成指南

## Vue 3 组件示例

### 聊天组件

```vue
<template>
  <div class="chat">
    <div class="messages">
      <div v-for="msg in messages" :key="msg.id" :class="msg.role">
        {{ msg.content }}
      </div>
    </div>
    <input v-model="input" @keyup.enter="send" placeholder="输入问题..." />
  </div>
</template>

<script setup>
import { ref } from 'vue'

const messages = ref([])
const input = ref('')
const token = ref(localStorage.getItem('token'))

async function send() {
  if (!input.value.trim()) return

  messages.value.push({ role: 'user', content: input.value })
  const question = input.value
  input.value = ''

  // 添加空的助手消息
  messages.value.push({ role: 'assistant', content: '' })
  const lastIdx = messages.value.length - 1

  const response = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token.value}`
    },
    body: JSON.stringify({
      message: question,
      document_ids: ['your-doc-id'],
      stream: true
    })
  })

  const reader = response.body.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const chunk = decoder.decode(value)
    for (const line of chunk.split('\n')) {
      if (line.startsWith('data: ')) {
        const event = JSON.parse(line.slice(6))
        if (event.type === 'token') {
          messages.value[lastIdx].content += event.data.content
        }
      }
    }
  }
}
</script>
```

### 文档上传组件

```vue
<template>
  <div class="upload">
    <input type="file" @change="upload" accept=".pdf,.docx,.md,.txt" />
    <div v-if="status">{{ status }}</div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const status = ref('')

async function upload(e) {
  const file = e.target.files[0]
  if (!file) return

  status.value = '上传中...'

  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch('/api/v1/documents/upload', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` },
    body: formData
  })

  const doc = await res.json()
  status.value = `已上传，ID: ${doc.id}`

  // 轮询状态
  pollStatus(doc.id)
}

async function pollStatus(docId) {
  const res = await fetch(`/api/v1/documents/${docId}/status`, {
    headers: { 'Authorization': `Bearer ${token}` }
  })
  const data = await res.json()

  if (data.status === 'completed') {
    status.value = '处理完成！'
  } else if (data.status === 'failed') {
    status.value = '处理失败'
  } else {
    status.value = `处理中 ${data.processing_progress}%`
    setTimeout(() => pollStatus(docId), 2000)
  }
}
</script>
```

---

# 安全最佳实践

## Token 安全

### 存储建议

| 存储方式 | 安全性 | 建议 |
|----------|--------|------|
| localStorage | 低 | 仅开发环境 |
| httpOnly Cookie | 高 | 生产环境推荐 |
| 内存 | 中 | 单页应用可用 |

## 输入验证

```python
# 后端已做验证，前端也应检查
def validate_input(message):
    if len(message) > 10000:
        raise ValueError("消息过长")
    return message.strip()
```

## CORS 配置

生产环境应限制允许的域名：

```python
# 后端配置示例
CORS_ORIGINS = ["https://your-domain.com"]
```

---

# 性能优化建议

## 前端优化

### 1. 防抖处理

```javascript
// 避免频繁请求
function debounce(fn, delay = 300) {
  let timer
  return (...args) => {
    clearTimeout(timer)
    timer = setTimeout(() => fn(...args), delay)
  }
}

const debouncedSearch = debounce(search, 500)
```

### 2. 请求取消

```javascript
let controller = null

async function chat(message) {
  // 取消上一个请求
  if (controller) controller.abort()
  controller = new AbortController()

  await fetch('/api/v1/chat/stream', {
    signal: controller.signal,
    // ...
  })
}
```

## 后端参数调优

| 场景 | top_k | reranker | 预期延迟 |
|------|-------|----------|----------|
| 快速响应 | 3 | 关闭 | < 2s |
| 平衡模式 | 5 | 关闭 | 2-4s |
| 高精度 | 10 | 开启 | 4-8s |

## 批量操作

```python
# 批量上传文档
files = ["doc1.pdf", "doc2.pdf", "doc3.pdf"]
for f in files:
    client.upload_document(f)

# 并行等待处理
import asyncio
await asyncio.gather(*[wait_for(doc_id) for doc_id in doc_ids])
```

---

*文档版本：3.0 | 最后更新：2024*

---

# 评估系统 (RAGAS)

## 什么是 RAGAS？

RAGAS 是 RAG 系统的评估框架，用于衡量回答质量：

| 指标 | 说明 | 范围 |
|------|------|------|
| `faithfulness` | 忠实度：回答是否基于检索内容 | 0-1 |
| `answer_relevancy` | 相关性：回答是否切题 | 0-1 |
| `context_precision` | 上下文精度 | 0-1 |

## 创建评估任务

```bash
POST /api/v1/evaluations/ragas/runs
```

```json
{
  "conversation_id": "对话ID",
  "metrics": ["faithfulness", "answer_relevancy"],
  "max_turns": 10
}
```

## 查看评估结果

```bash
GET /api/v1/evaluations/ragas/runs/{run_id}
```

**响应示例：**
```json
{
  "id": "run-uuid",
  "status": "completed",
  "scores": {
    "faithfulness": 0.85,
    "answer_relevancy": 0.92
  }
}
```

## 回归测试

用于持续监控 RAG 质量：

```bash
# 创建测试用例
POST /api/v1/evaluations/ragas/regression/cases

# 运行回归测试
POST /api/v1/evaluations/ragas/regression/runs
```

## 回归 Leaderboard（按检索指标排序）

按回归 run 的 `summary` 指标排序，返回一个轻量 leaderboard，并附带 `retrieval_config_hash`（用于按检索配置分组/对比；PII-safe）。

```bash
GET /api/v1/evaluations/ragas/regression/runs/leaderboard?dataset_id={dataset_id}&metric_key=retrieval_mrr&limit=20
```

**常用 metric_key：**
- `retrieval_recall`
- `retrieval_hit_at_20`
- `retrieval_mrr`
- `retrieval_ndcg_at_20`
- `abstain_rate`

**响应示例：**
```json
{
  "metric_key": "retrieval_mrr",
  "items": [
    {
      "run_id": "run-uuid",
      "status": "completed",
      "created_at": "2024-01-01T00:00:00Z",
      "finished_at": "2024-01-01T00:01:00Z",
      "metric_key": "retrieval_mrr",
      "metric_value": 0.42,
      "retrieval_config_hash": "1a2b3c4d5e6f..."
    }
  ]
}
```

---

# 提示词模板管理

## 为什么需要模板？

- 统一管理 Prompt
- 支持 A/B 测试
- 版本控制

## 创建模板

```bash
POST /api/v1/prompt-templates
```

```json
{
  "name": "客服模板",
  "content": "你是客服助手。\n\n上下文：{context}\n\n问题：{question}",
  "variables": ["context", "question"],
  "category": "chat"
}
```

## 在对话中使用模板

```json
{
  "message": "问题内容",
  "document_ids": ["doc-id"],
  "prompt_template_id": "模板UUID"
}
```

## A/B 测试

```json
{
  "prompt_ab_experiment_key": "experiment_1"
}
```

---

# 系统配置 API

## 获取当前配置

```bash
GET /api/v1/settings
```

**响应包含：**
- LLM 配置
- 向量数据库配置
- RAG 参数
- 功能开关

## 功能开关

| 开关 | 说明 |
|------|------|
| `kg_enabled` | 知识图谱 |
| `docling_enabled` | Docling 解析器 |
| `mineru_enabled` | MinerU 解析器 |

## 更新配置

```bash
PUT /api/v1/settings
```

> 需要管理员权限

---

# 术语表

## 核心概念

| 术语 | 英文 | 解释 |
|------|------|------|
| RAG | Retrieval-Augmented Generation | 检索增强生成，结合检索和生成的 AI 技术 |
| 向量 | Vector | 文本的数学表示，用于语义相似度计算 |
| 嵌入 | Embedding | 将文本转换为向量的过程 |
| 分块 | Chunking | 将长文档切分为小段落的过程 |
| 检索 | Retrieval | 根据问题查找相关文档块 |
| 重排序 | Reranking | 对检索结果重新排序以提高精度 |
| 知识图谱 | Knowledge Graph (KG) | 从文档中提取的实体和关系网络 |

## 技术术语

| 术语 | 解释 |
|------|------|
| JWT | JSON Web Token，用于身份认证的令牌格式 |
| SSE | Server-Sent Events，服务器推送事件，用于流式响应 |
| Top-K | 检索返回的文档块数量 |
| Score Threshold | 相似度阈值，过滤低相关性结果 |
| Hybrid Search | 混合检索，结合向量和关键词搜索 |
| MMR | 最大边际相关性，用于结果多样化 |
| Token | 文本的最小单位（词或子词） |

## 文件格式

| 格式 | 说明 |
|------|------|
| PDF | 便携式文档格式，支持 OCR |
| DOCX | Microsoft Word 文档 |
| MD | Markdown 标记语言文档 |
| TXT | 纯文本文件 |
| HTML | 网页文档 |
| XLSX | Microsoft Excel 表格 |

---

# API 模块索引

## 按功能分类

### 用户认证
| 接口 | 方法 | 说明 |
|------|------|------|
| `/auth/register` | POST | 用户注册 |
| `/auth/login` | POST | 用户登录 |
| `/auth/me` | GET | 获取当前用户 |

### 文档管理
| 接口 | 方法 | 说明 |
|------|------|------|
| `/documents/upload` | POST | 上传文档 |
| `/documents/` | GET | 文档列表 |
| `/documents/{id}` | GET | 文档详情 |
| `/documents/{id}/status` | GET | 处理状态 |
| `/documents/{id}` | DELETE | 删除文档 |

### 对话问答
| 接口 | 方法 | 说明 |
|------|------|------|
| `/chat/stream` | POST | 流式对话 |
| `/chat/conversations` | POST | 创建对话 |
| `/chat/conversations` | GET | 对话列表 |
| `/chat/conversations/{id}/messages` | GET | 消息历史 |
| `/chat/conversations/{id}` | DELETE | 删除对话 |

### 数据集管理
| 接口 | 方法 | 说明 |
|------|------|------|
| `/datasets/` | POST | 创建数据集 |
| `/datasets/` | GET | 数据集列表 |
| `/datasets/{id}` | GET | 数据集详情 |
| `/datasets/{id}` | PATCH | 更新数据集 |
| `/datasets/{id}` | DELETE | 删除数据集 |

### 知识图谱
| 接口 | 方法 | 说明 |
|------|------|------|
| `/kg/graph` | GET | 获取图谱数据 |
| `/kg/graph/expand` | GET | 展开节点 |
| `/kg/graph/search` | GET | 搜索节点 |
| `/kg/stats` | GET | 图谱统计 |
| `/kg/documents/{id}/extract` | POST | 触发抽取 |

### 系统管理
| 接口 | 方法 | 说明 |
|------|------|------|
| `/settings` | GET | 获取配置 |
| `/settings` | PUT | 更新配置 |
| `/settings/status` | GET | 系统状态 |
| `/health` | GET | 健康检查 |
| `/health/ready` | GET | 就绪探针 |

### 调试工具
| 接口 | 方法 | 说明 |
|------|------|------|
| `/rag/retrieve-preview` | POST | 检索预览 |
| `/rag/prompt-preview` | POST | 提示词预览 |
| `/evaluations/ragas/runs` | POST | 创建评估 |
| `/evaluations/ragas/runs/{id}` | GET | 评估结果 |

---

# 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| 1.0 | 2024-01 | 初始版本，基础 API |
| 2.0 | 2024-06 | 添加错误码、RAG 参数、调试指南 |
| 3.0 | 2024-12 | 添加 KG、评估系统、前端集成 |

---

# 快速参考卡片

## 最常用接口

```bash
# 登录
POST /api/v1/auth/login

# 上传文档
POST /api/v1/documents/upload

# 检查状态
GET /api/v1/documents/{id}/status

# 开始对话
POST /api/v1/chat/stream
```

## 必备请求头

```
Authorization: Bearer <token>
Content-Type: application/json
```

## 状态码速查

| 码 | 含义 | 处理方式 |
|----|------|----------|
| 200 | 成功 | 正常处理 |
| 401 | 未认证 | 重新登录 |
| 404 | 不存在 | 检查 ID |
| 502 | LLM 错误 | 检查 API Key |

---

*MimirQ API 文档 - 让知识触手可及*

---

# 高级功能：文档处理管道

> Pipeline API 提供文档解析、分块、清洗的预览和调试功能

## 获取管道能力

查询系统支持的解析器和分块策略：

```bash
GET /api/v1/pipeline/capabilities
```

**响应示例：**
```json
{
  "default_parser_backend": "auto",
  "default_chunk_strategy": "langchain_recursive",
  "pdf_backends": [
    {"name": "auto", "available": true, "notes": "自动选择最佳解析器"},
    {"name": "basic", "available": true, "notes": null},
    {"name": "mineru", "available": true, "notes": null},
    {"name": "docling", "available": false, "notes": "Set DOCLING_ENABLED=true"}
  ],
  "chunk_strategies": [
    {"name": "langchain_recursive", "available": true, "notes": null},
    {"name": "markdown_header", "available": true, "notes": null}
  ]
}
```

## 解析预览

上传文件并预览解析结果（不保存）：

```bash
POST /api/v1/pipeline/parse-preview
Content-Type: multipart/form-data
```

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| file | File | 要解析的文件 |
| parser_backend | string | 解析器：auto/basic/mineru/docling 等 |

**响应：**
```json
{
  "markdown": "# 文档标题\n\n这是解析后的内容...",
  "images": [
    {"id": "img-001", "url": "/uploads/tenant/images/xxx.png"}
  ],
  "parser_used": "mineru",
  "parse_time_ms": 1234
}
```

## 分块预览

预览 Markdown 文本的分块结果：

```bash
POST /api/v1/pipeline/chunk-preview
```

**请求体：**
```json
{
  "markdown": "# 标题\n\n这是一段文本...",
  "chunk_strategy": "langchain_recursive",
  "chunk_size": 1000,
  "chunk_overlap": 200
}
```

**响应：**
```json
{
  "chunks": [
    {
      "index": 0,
      "content": "# 标题\n\n这是一段文本...",
      "start_offset": 0,
      "end_offset": 500,
      "metadata": {"heading": "标题"}
    }
  ],
  "total_chunks": 5
}
```

## 清洗预览

预览文本清洗效果（去噪、格式化）：

```bash
POST /api/v1/pipeline/clean-preview
```

**请求体：**
```json
{
  "markdown": "原始文本...",
  "use_default_rules": true,
  "normalize_line_endings": true,
  "collapse_blank_lines": true,
  "remove_toc_lines": true,
  "pii_anonymize": false
}
```

**响应：**
```json
{
  "markdown": "清洗后的文本...",
  "changed": true,
  "applied_rules": ["normalize_whitespace", "remove_toc"],
  "input_chars": 1000,
  "output_chars": 850
}
```

## 关键词提取

从文本中提取关键词：

```bash
POST /api/v1/pipeline/extract-keywords
```

**请求体：**
```json
{
  "text": "要提取关键词的文本内容...",
  "provider": "jieba",
  "top_k": 10
}
```

**支持的提供者：**
| 提供者 | 说明 |
|--------|------|
| `jieba` | 结巴分词（默认） |
| `jieba_tfidf` | TF-IDF 算法 |
| `jieba_textrank` | TextRank 算法 |
| `hanlp` | HanLP（需安装） |
| `simple` | 简单词频统计 |

## LLM 智能清洗

使用 LLM 进行智能文本清洗：

```bash
POST /api/v1/pipeline/llm-clean-preview
```

**请求体：**
```json
{
  "markdown": "需要清洗的文本...",
  "model": "gpt-4o-mini",
  "temperature": 0.0,
  "max_chars": 10000
}
```

---

# 用户反馈 API

> 收集用户对 AI 回答的评价，用于持续优化系统

## 提交反馈

对助手消息提交评分和反馈：

```bash
POST /api/v1/feedback/messages
```

**请求体：**
```json
{
  "message_id": "msg-uuid-12345",
  "rating": 5,
  "reason": "回答准确且有帮助",
  "tags": ["accurate", "helpful"],
  "expected_answer": "可选：期望的正确答案"
}
```

**评分说明：**
| 评分 | 含义 |
|------|------|
| 1 | 非常差 |
| 2 | 较差 |
| 3 | 一般 |
| 4 | 较好 |
| 5 | 非常好 |

**响应 (201)：**
```json
{
  "id": "feedback-uuid",
  "message_id": "msg-uuid-12345",
  "rating": 5,
  "reason": "回答准确且有帮助",
  "created_at": "2024-01-01T00:00:00Z"
}
```

## 查询反馈列表

```bash
GET /api/v1/feedback/messages?skip=0&limit=50
```

**查询参数：**
| 参数 | 说明 |
|------|------|
| conversation_id | 按对话筛选 |
| message_id | 按消息筛选 |
| min_rating | 最低评分 |
| max_rating | 最高评分 |

## 反馈转 EvidenceItem（Hardcase 草稿）

将一条反馈转换为指定 `EvidenceSuite` 下的 **draft** `EvidenceItem`，用于构建企业级优化闭环：
`feedback -> draft evidence -> reviewed/approved -> sync -> regression runs/leaderboard`。

```bash
POST /api/v1/feedback/messages/{feedback_id}/to-evidence-item
```

**请求体：**
```json
{
  "suite_id": "evidence-suite-uuid",
  "tags": ["hardcase", "needs_fix"],
  "extra": {
    "priority": "P1"
  }
}
```

**响应 (201)：**
```json
{
  "id": "evidence-item-uuid",
  "suite_id": "evidence-suite-uuid",
  "dataset_id": "dataset-uuid",
  "status": "draft",
  "query": "用户问题（从会话中推断）",
  "tags": ["hardcase", "needs_fix"],
  "reference_sources": [
    {
      "document_id": "doc-uuid",
      "chunk_id": "chunk-uuid"
    }
  ],
  "rag_config_snapshot": {
    "retrieval_config_hash": "1a2b3c4d5e6f..."
  },
  "created_at": "2024-01-01T00:00:00Z"
}
```

**说明：**
- 会校验：EvidenceSuite 存在且未归档、当前账号可读该 suite 的 dataset。
- 若反馈对应的 dataset 与 suite.dataset 不一致，会返回 `400`（避免跨数据集污染）。
- `reference_sources` 会优先从 assistant message 的 `citations` 抽取；若为空，会回退到 trace 的 `citations`（best-effort）。
- `rag_config_snapshot` 会保存 trace 中的检索配置快照（包含 `retrieval_config_hash`，用于 leaderboard/回归对比；PII-safe）。

---

# 系统元数据 API

> 获取系统版本和功能状态信息

## 获取元数据

```bash
GET /api/v1/meta
```

**响应：**
```json
{
  "name": "MimirQ",
  "api_version": "v1",
  "time": "2024-01-01T00:00:00Z",
  "build": {
    "sha": "abc1234",
    "time": "2024-01-01"
  },
  "features": {
    "auth_mode": "jwt",
    "vector_backend": "milvus",
    "task_queue_enabled": true
  },
  "runtime": {
    "python": "3.11.0",
    "platform": "Linux-5.15.0"
  }
}
```

---

# 分块策略详解

> 选择合适的分块策略可以显著提升检索效果

## 通用策略

| 策略 | 适用场景 | 说明 |
|------|----------|------|
| `auto` | 通用 | 自动识别文档类型并选择最佳策略 |
| `langchain_recursive` | 通用 | 递归字符分割，最常用 |
| `markdown_header` | Markdown | 按标题层级分割 |
| `sentence_window` | 精细检索 | 句子级分割，带上下文窗口 |

## 专业文档策略

| 策略 | 适用场景 |
|------|----------|
| `paper` | 学术论文（按章节分割） |
| `book_structured` | 书籍（按章节分割） |
| `laws_structured` | 法律文档（按条款分割） |
| `resume_structured` | 简历（按模块分割） |
| `presentation_slides` | PPT/演示文稿 |

## 结构化数据策略

| 策略 | 适用场景 |
|------|----------|
| `csv_rows` | CSV 表格数据 |
| `spreadsheet_sheet` | Excel 工作表 |
| `markdown_table` | Markdown 表格 |
| `json` | JSON 数据 |

## 技术文档策略

| 策略 | 适用场景 |
|------|----------|
| `api_reference` | API 文档 |
| `changelog` | 更新日志 |
| `dockerfile` | Dockerfile |
| `yaml_manifest` | YAML 配置 |
| `sql_schema` | SQL DDL |

## 对话/日志策略

| 策略 | 适用场景 |
|------|----------|
| `chat_history` | 聊天记录 |
| `email_thread` | 邮件往来 |
| `log_events` | 日志文件 |
| `meeting_minutes` | 会议纪要 |

---

# 部署指南

## 环境要求

| 组件 | 最低版本 | 推荐版本 |
|------|----------|----------|
| Python | 3.10 | 3.11+ |
| PostgreSQL | 14 | 16 |
| Milvus | 2.3 | 2.4+ |
| Redis | 6.0 | 7.0+ |

## 快速启动

### 1. 克隆项目

```bash
git clone https://github.com/your-org/mimirq.git
cd mimirq
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，配置必要参数
```

### 3. 必要配置项

```bash
# 数据库
DATABASE_URL=postgresql://user:pass@localhost:5432/mimirq

# 向量数据库
MILVUS_HOST=localhost
MILVUS_PORT=19530

# LLM 配置
LLM_API_KEY=your-api-key
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

### 4. 启动服务

```bash
# 安装依赖
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# 数据库迁移
alembic upgrade head

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker 部署

```bash
# 构建镜像
docker build -t mimirq:latest .

# 启动容器
docker run -d \
  --name mimirq \
  -p 8000:8000 \
  -e DATABASE_URL=postgresql://... \
  -e LLM_API_KEY=your-key \
  mimirq:latest
```

## 生产环境建议

| 项目 | 建议 |
|------|------|
| 进程管理 | 使用 Gunicorn + Uvicorn workers |
| 反向代理 | Nginx / Traefik |
| HTTPS | 必须启用 |
| 监控 | Prometheus + Grafana |

---

*如有问题，请联系开发团队或查看项目 README*
