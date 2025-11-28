# 🚀 快速启动指南

## 查看新的 Logo 系统

### 1. 启动前端开发服务器

```bash
cd frontend
npm install  # 如果还没安装依赖
npm run dev
```

### 2. 访问以下页面

#### 📊 Logo 预览页面 (推荐首先查看)
```
http://localhost:3000/logos-preview
```
这个页面展示:
- 所有 8 个品牌图标
- 不同尺寸对比
- 不同背景效果
- 使用说明

#### ⚙️ 设置页面 (模型配置)
```
http://localhost:3000/settings
```
查看图标在实际页面中的应用:
- 模型提供商卡片
- 配置对话框
- 网格布局展示

### 3. 测试图标功能

在设置页面:
1. 点击任意模型提供商卡片
2. 查看配置对话框中的品牌图标
3. 测试不同提供商的图标显示

## 📁 文件位置

### Logo 文件
```
frontend/public/logos/
├── openai.svg          # OpenAI 图标
├── anthropic.svg       # Anthropic 图标
├── deepseek.svg        # DeepSeek 图标
├── zhipu.svg           # 智谱 AI 图标
├── qwen.svg            # 通义千问图标
├── moonshot.svg        # Moonshot 图标
├── ollama.svg          # Ollama 图标
└── local.svg           # 本地 Embedding 图标
```

### 关键组件
```
frontend/components/provider-icon.tsx    # 图标组件
frontend/components/model-provider-card.tsx   # 提供商卡片
frontend/app/settings/page.tsx           # 设置页面
```

## 🔄 替换为真实官方 Logo

### 方法 1: 从官网下载

访问品牌官网 → 下载 Logo → 重命名 → 替换文件

示例:
```bash
# 下载 OpenAI 官方 Logo
curl -o frontend/public/logos/openai.svg https://example.com/openai-logo.svg

# 清除缓存并重启
cd frontend
rm -rf .next
npm run dev
```

### 方法 2: 使用 Brandfetch

1. 访问 https://brandfetch.com/
2. 搜索品牌名称 (如 "OpenAI")
3. 下载 SVG 格式 Logo
4. 重命名为对应文件名
5. 替换到 `public/logos/` 目录

### 方法 3: 使用 Simple Icons

```bash
# 安装 simple-icons 库 (可选)
npm install simple-icons

# 或直接从网站下载
# https://simpleicons.org/?q=openai
```

## ✅ 验证清单

- [ ] 前端服务器启动成功
- [ ] 访问 `/logos-preview` 页面正常
- [ ] 所有 8 个图标都能正常显示
- [ ] 访问 `/settings` 页面正常
- [ ] 点击提供商卡片能弹出配置对话框
- [ ] 图标在不同尺寸下显示清晰

## 🐛 故障排查

### 图标不显示?

```bash
# 1. 检查文件是否存在
ls -l frontend/public/logos/*.svg

# 2. 验证文件名 (必须全小写)
# ✅ openai.svg
# ❌ OpenAI.svg

# 3. 清除 Next.js 缓存
rm -rf frontend/.next

# 4. 重启开发服务器
cd frontend
npm run dev
```

### 显示 404 错误?

检查文件路径:
```
正确: /logos/openai.svg
错误: /public/logos/openai.svg
```

Next.js 的 `public` 目录会映射到根路径。

### 图标显示模糊?

确保使用 SVG 格式而非 PNG/JPG:
```bash
file frontend/public/logos/openai.svg
# 输出应该是: SVG 格式
```

## 📚 相关文档

- `/frontend/public/logos/README.md` - Logo 使用指南
- `/LOGO_UPDATE_SUMMARY.md` - 更新总结
- `/frontend/MODEL_PROVIDER_GUIDE.md` - 模型配置指南

## 🎯 下一步

1. **替换真实 Logo**: 从官网获取正式的品牌资源
2. **优化 SVG**: 使用 SVGO 压缩文件体积
3. **配置模型**: 在设置页面配置你的 API Key
4. **测试对话**: 配置完成后测试 AI 对话功能

## 💬 获取帮助

如有问题,请查看:
- GitHub Issues
- 项目文档
- 社区讨论

---

快速启动成功后,开始配置你的第一个 AI 模型吧! 🎉
