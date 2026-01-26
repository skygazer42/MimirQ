# OpenTelemetry（OTEL）与 Phoenix 可观测性

MimirQ 后端内置 **OpenTelemetry tracing**（默认关闭）。开启后可将 FastAPI 请求链路与 httpx 出站请求导出到 OTLP Collector（例如 Arize Phoenix）。

## 1) 开启 OTEL（后端）

在后端 `.env` 中配置：

```bash
OTEL_ENABLED=true
OTEL_SERVICE_NAME=mimirq

# OTLP gRPC endpoint（默认 exporter 为 gRPC）
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# 可选：自定义 headers（例如 Basic/Bearer）
OTEL_EXPORTER_OTLP_HEADERS=

# 导出超时（秒）
OTEL_EXPORTER_OTLP_TIMEOUT_SEC=10
```

说明：

- `OTEL_ENABLED=true` 后，会自动：
  - 初始化 tracer provider + OTLP exporter
  - instrument FastAPI（入站）
  - instrument httpx（出站）
- 若 OTEL 依赖缺失或 exporter 初始化失败，会记录 warning 并自动降级（不会影响主功能）。

## 2) 本地运行 Phoenix（推荐）

Phoenix 自带 UI 与 OTLP Collector。官方示例（Docker）：

```bash
docker run -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest
```

- UI：http://localhost:6006
- OTLP gRPC：`http://localhost:4317`

将后端 `OTEL_EXPORTER_OTLP_ENDPOINT` 指向 Phoenix 的 4317 端口后，启动 MimirQ，访问任意 API（如 `/docs` / `/api/v1/chat/stream`）即可在 Phoenix 中看到 traces。

## 3) 重要：Phoenix Cloud / 协议差异

当前 MimirQ 后端 exporter 使用 **OTLP gRPC**（`opentelemetry-exporter-otlp-proto-grpc`）。

Phoenix Cloud 在部分时期可能仅支持 **HTTP/protobuf** 方式收集 traces（以 Phoenix 官方文档为准）。如果你的目标环境不支持 gRPC：

1) 建议先使用 **OpenTelemetry Collector** 做协议转换（应用 → collector(gRPC) → Phoenix(http)），或  
2) 在代码层增加 HTTP exporter（未来可选增强项）。

## 4) 排查清单

- 没有 trace：
  - 确认 `OTEL_ENABLED=true`
  - 确认 `OTEL_EXPORTER_OTLP_ENDPOINT` 可达（容器网络里注意使用服务名而非 localhost）
- Phoenix 能打开但无数据：
  - 确认 Phoenix 暴露了 4317（gRPC）端口
  - 确认没有被代理/网关拦截 gRPC

