@echo off
echo ================================
echo MimirQ - AI 知识库助手
echo ================================
echo.

REM 检查 Docker 是否运行
docker version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker 未运行，请先启动 Docker Desktop
    pause
    exit /b 1
)

REM 检查环境变量文件
if not exist "backend\.env" (
    echo ⚠️  未找到 backend\.env 文件，正在创建...
    copy backend\.env.example backend\.env
    echo ✅ 已创建 backend\.env，请编辑文件填入 OPENAI_API_KEY
    echo.
    echo 请执行以下步骤：
    echo 1. 编辑 backend\.env 文件
    echo 2. 填入你的 OPENAI_API_KEY=sk-your-api-key
    echo 3. 再次运行 start.bat
    pause
    exit /b 0
)

if not exist "frontend\.env.local" (
    echo ⚠️  未找到 frontend\.env.local 文件，正在创建...
    copy frontend\.env.local.example frontend\.env.local
)

echo 📦 正在启动服务...
echo.

REM 启动 Docker Compose
docker-compose up -d

echo.
echo ✅ 服务启动成功！
echo.
echo 📋 服务地址：
echo   🌐 前端:      http://localhost:3000
echo   🔌 后端 API:  http://localhost:8000
echo   📖 API 文档:  http://localhost:8000/docs
echo   💾 ChromaDB:  http://localhost:8001
echo.
echo 📝 查看日志: docker-compose logs -f
echo 🛑 停止服务: docker-compose down
echo.
pause
