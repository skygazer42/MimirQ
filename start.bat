@echo off
setlocal

docker compose up -d --build
if %errorlevel% neq 0 (
  docker-compose up -d --build
)

echo Frontend: http://localhost:3000
echo Backend:  http://localhost:8000/docs
