
import os

from start_local_api import ensure_local_model_config, ensure_models


def main() -> None:
    ensure_models(["vlm"])
    ensure_local_model_config()
    args = [
        "mineru-vllm-server",
        "--host",
        "0.0.0.0",
        "--port",
        "30000",
        "--gpu-memory-utilization",
        (os.environ.get("MINERU_VLM_GPU_MEMORY_UTILIZATION") or "0.8").strip() or "0.8",
    ]
    os.execvp(args[0], args)


if __name__ == "__main__":
    main()
