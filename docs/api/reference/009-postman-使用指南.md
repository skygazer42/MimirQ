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
