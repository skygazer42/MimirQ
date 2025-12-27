@echo off
setlocal

docker compose down
if %errorlevel% neq 0 (
  docker-compose down
)
