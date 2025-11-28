#!/bin/bash

echo "🚀 MimirQ - AI 知识库助手"
echo "=========================="
echo ""

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi

# 检查 Docker Compose 是否安装
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose 未安装，请先安装 Docker Compose"
    exit 1
fi

# 检查环境变量文件
if [ ! -f "backend/.env" ]; then
    echo "⚠️  未找到 backend/.env 文件，正在创建..."
    cp backend/.env.example backend/.env
    echo "✅ 已创建 backend/.env，请编辑文件填入 OPENAI_API_KEY"
    echo ""
    echo "请执行以下步骤："
    echo "1. 编辑 backend/.env 文件"
    echo "2. 填入你的 OPENAI_API_KEY=sk-your-api-key"
    echo "3. 再次运行 ./start.sh"
    exit 0
fi

if [ ! -f "frontend/.env.local" ]; then
    echo "⚠️  未找到 frontend/.env.local 文件，正在创建..."
    cp frontend/.env.local.example frontend/.env.local
fi

echo "📦 正在启动服务..."
echo ""

# 启动 Docker Compose
docker-compose up -d

echo ""
echo "✅ 服务启动成功！"
echo ""
echo "📋 服务地址："
echo "  🌐 前端:        http://localhost:3000"
echo "  🔌 后端 API:    http://localhost:8000"
echo "  📖 API 文档:    http://localhost:8000/docs"
echo "  💾 Milvus:      http://localhost:19530"
echo "  📊 Milvus UI:   http://localhost:9091"
echo "  🗄️  MinIO:      http://localhost:9001"
echo ""
echo "📝 查看日志: docker-compose logs -f"
echo "🛑 停止服务: docker-compose down"
echo ""
