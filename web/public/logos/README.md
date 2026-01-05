# 品牌 Logo 资源

本目录包含各 AI 模型提供商的官方 Logo 图标。

## 当前图标

| 提供商 | 文件名 | 状态 | 说明 |
|--------|--------|------|------|
| OpenAI | `openai.svg` | ✅ | OpenAI 官方品牌色 (#10A37F) |
| Anthropic | `anthropic.svg` | ✅ | Anthropic Claude 品牌色 (#CC785C) |
| DeepSeek | `deepseek.svg` | ✅ | DeepSeek 品牌蓝色 (#0066FF) |
| 智谱 AI | `zhipu.svg` | ✅ | 紫色渐变设计 |
| 通义千问 | `qwen.svg` | ✅ | 阿里云蓝色 (#0EA5E9) |
| Moonshot AI | `moonshot.svg` | ✅ | 月亮图标,靛蓝色 (#4F46E5) |
| Ollama | `ollama.svg` | ✅ | 黑色背景,简约设计 |
| 本地 Embedding | `local.svg` | ✅ | 绿色文件夹图标 (#10B981) |

## 如何使用真实的官方 Logo

### 方法 1: 手动下载官方 Logo

访问各提供商官网,下载官方品牌资源:

1. **OpenAI**: https://openai.com/brand
2. **Anthropic**: https://www.anthropic.com/press
3. **DeepSeek**: https://www.deepseek.com/ (从官网截取)
4. **智谱 AI**: https://open.bigmodel.cn/ (联系获取)
5. **通义千问**: https://tongyi.aliyun.com/ (阿里云品牌中心)
6. **Moonshot**: https://www.moonshot.cn/ (官网)
7. **Ollama**: https://ollama.ai/ (GitHub 仓库)

### 方法 2: 使用官方 CDN 链接

某些提供商可能提供 CDN 链接,可直接引用:

```tsx
<Image
  src="https://cdn.openai.com/logo.svg"
  alt="OpenAI"
  width={32}
  height={32}
/>
```

### 方法 3: 品牌资源包

从以下网站获取高质量 Logo:

- **Brandfetch**: https://brandfetch.com/
- **Worldvectorlogo**: https://worldvectorlogo.com/
- **Simple Icons**: https://simpleicons.org/

## 替换 Logo 的步骤

1. 下载官方 Logo (建议 SVG 格式)
2. 重命名为对应的提供商 ID:
   - `openai.svg`
   - `anthropic.svg`
   - `deepseek.svg`
   - 等等...
3. 放入 `/public/logos/` 目录
4. 确保文件尺寸为 32x32 或保持纵横比

## Logo 设计规范

为了保持界面一致性,所有 Logo 应遵循以下规范:

- **格式**: SVG (矢量格式,支持缩放)
- **尺寸**: 32x32 像素基准
- **背景**: 可以有圆角矩形背景 (6px 圆角)
- **颜色**: 保持品牌原色
- **留白**: 保持适当的内边距

## 许可证说明

所有品牌 Logo 归其各自所有者所有:

- OpenAI™ 是 OpenAI, LP 的商标
- Claude™ 和 Anthropic™ 是 Anthropic, PBC 的商标
- DeepSeek™ 是 DeepSeek AI 的商标
- 通义千问™ 是阿里云的商标
- Moonshot™ 和 Kimi™ 是 Moonshot AI 的商标
- Ollama™ 是 Ollama Inc. 的商标

本项目中的 Logo 仅用于标识相应的 AI 服务,不作商业用途。

## 自定义 Logo

如果你想自定义某个提供商的 Logo:

1. 创建一个 32x32 的 SVG 文件
2. 使用 Figma/Illustrator/Inkscape 设计
3. 导出为 SVG
4. 确保 SVG 代码干净(移除不必要的元素)
5. 替换对应的文件

示例 SVG 模板:

```svg
<svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="32" height="32" rx="6" fill="#YOUR_COLOR"/>
  <!-- 你的图标内容 -->
</svg>
```

## 问题排查

### Logo 不显示?

1. 检查文件名是否正确 (全小写,与 provider id 匹配)
2. 确认文件在 `/public/logos/` 目录下
3. 检查 SVG 文件是否有效 (在浏览器中打开测试)
4. 清除 Next.js 缓存: `rm -rf .next`

### Logo 显示模糊?

- 确保使用 SVG 格式,而不是 PNG/JPG
- 检查 `viewBox` 属性是否正确
- 如果必须使用位图,提供 @2x 或 @3x 版本

## 贡献

如果你有更好的官方 Logo 资源,欢迎提交 PR!

请确保:
- Logo 来自官方渠道或获得授权
- 文件大小 < 50KB
- SVG 代码已优化(使用 SVGO)
- 符合品牌使用规范

---

最后更新: 2024-11-28
