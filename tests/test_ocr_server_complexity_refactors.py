import asyncio
import inspect
import io
import shutil
import signal
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, UploadFile

from docker.olmocr import server as olmocr_server
from docker.paddlevl import server as paddlevl_server
from docker.qianfanocr import server as qianfanocr_server


class _Request:
    def __init__(self, *, disconnected: bool = False) -> None:
        self._disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self._disconnected


class _ManagedTempDir:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> str:
        self.path.mkdir(parents=True, exist_ok=True)
        return str(self.path)

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


class _FakeAsyncProcess:
    def __init__(self) -> None:
        self.pid = 321
        self.returncode: int | None = None
        self.stdout = io.BytesIO()

    async def wait(self) -> int:
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -signal.SIGTERM

    def kill(self) -> None:
        self.returncode = -signal.SIGKILL


class _FakePopen:
    def __init__(self) -> None:
        self.pid = 456
        self.returncode: int | None = None
        self.wait_calls = 0

    def poll(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise subprocess.TimeoutExpired(cmd="paddleocr", timeout=timeout or 0)
        self.returncode = -signal.SIGKILL
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -signal.SIGTERM

    def kill(self) -> None:
        self.returncode = -signal.SIGKILL


def _upload_file(name: str, content: bytes = b"payload") -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content))


def test_ocr_server_convert_signatures_stay_stable() -> None:
    assert str(inspect.signature(olmocr_server.convert)) == (
        "(request: starlette.requests.Request, file: "
        "typing.Annotated[fastapi.datastructures.UploadFile, File(PydanticUndefined)], "
        "output_format: typing.Annotated[str, Form(PydanticUndefined)] = 'markdown') -> "
        "dict[str, typing.Any]"
    )
    assert str(inspect.signature(paddlevl_server.convert)) == (
        "(file: typing.Annotated[fastapi.datastructures.UploadFile, File(PydanticUndefined)], "
        "output_format: typing.Annotated[str, Form(PydanticUndefined)] = 'markdown', "
        "dpi: typing.Annotated[int, Form(PydanticUndefined)] = 150, "
        "pipeline_version: typing.Annotated[str, Form(PydanticUndefined)] = '', "
        "device: typing.Annotated[str, Form(PydanticUndefined)] = '') -> "
        "starlette.responses.Response"
    )
    assert str(inspect.signature(qianfanocr_server.convert)) == (
        "(file: typing.Annotated[fastapi.datastructures.UploadFile, File(PydanticUndefined)], "
        "output_format: typing.Annotated[str, Form(PydanticUndefined)] = 'markdown', "
        "layout_as_thought: typing.Annotated[str, Form(PydanticUndefined)] = '') -> "
        "dict[str, typing.Any]"
    )


def test_olmocr_build_pipeline_command_includes_optional_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OLMOCR_SERVER_URL", "https://olm.example.test/v1")
    monkeypatch.setenv("OLMOCR_API_KEY", "secret")
    monkeypatch.setenv("OLMOCR_MODEL", "olm-model")
    monkeypatch.setenv("OLMOCR_GPU_MEMORY_UTILIZATION", "0.75")
    monkeypatch.setenv("OLMOCR_MAX_MODEL_LEN", "16384")
    monkeypatch.setenv("OLMOCR_MAX_SERVER_READY_TIMEOUT", "90")
    monkeypatch.setenv("OLMOCR_TENSOR_PARALLEL_SIZE", "2")
    monkeypatch.setenv("OLMOCR_DATA_PARALLEL_SIZE", "3")
    monkeypatch.setenv("OLMOCR_VLLM_PORT", "3111")
    monkeypatch.setenv("OLMOCR_EXTRA_ARGS", "--foo bar --baz=qux")

    cmd = olmocr_server._build_pipeline_command(workspace=tmp_path, input_name="input.pdf")

    assert cmd[:4] == ["python3", "-m", "olmocr.pipeline", str(tmp_path)]
    assert "--server" in cmd and "https://olm.example.test/v1" in cmd
    assert "--api_key" in cmd and "secret" in cmd
    assert "--model" in cmd and "olm-model" in cmd
    assert "--gpu-memory-utilization" in cmd and "0.75" in cmd
    assert "--max_model_len" in cmd and "16384" in cmd
    assert "--max_server_ready_timeout" in cmd and "90" in cmd
    assert "--tensor-parallel-size" in cmd and "2" in cmd
    assert "--data-parallel-size" in cmd and "3" in cmd
    assert "--port" in cmd and "3111" in cmd
    assert cmd[-3:] == ["--foo", "bar", "--baz=qux"]


@pytest.mark.asyncio
async def test_olmocr_run_pipeline_drains_buffered_output_after_process_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _BufferedStdout:
        def __init__(self) -> None:
            self.chunks = [b"buffered ", b"stdout\n", b""]
            self.read_calls = 0

        async def read(self, _size: int) -> bytes:
            self.read_calls += 1
            return self.chunks.pop(0)

    class _CompletedProcess:
        pid = 321
        returncode = 0

        def __init__(self) -> None:
            self.stdout = _BufferedStdout()

        async def wait(self) -> int:
            return self.returncode

    process = _CompletedProcess()

    async def _spawn(*_args: object, **_kwargs: object) -> _CompletedProcess:
        return process

    monkeypatch.setattr(olmocr_server.asyncio, "create_subprocess_exec", _spawn)

    result = await olmocr_server._run_pipeline(
        request=_Request(),
        workspace=tmp_path,
        input_name="input.pdf",
    )

    assert result == (0, "buffered stdout")
    assert process.stdout.read_calls == 3


@pytest.mark.asyncio
async def test_olmocr_run_pipeline_cancels_on_disconnect(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = _FakeAsyncProcess()
    terminated = False

    async def _spawn(*_args: object, **_kwargs: object) -> _FakeAsyncProcess:
        return process

    async def _terminate(target: _FakeAsyncProcess, **_kwargs: object) -> None:
        nonlocal terminated
        assert target is process
        terminated = True
        target.returncode = -signal.SIGTERM

    monkeypatch.setattr(olmocr_server.asyncio, "create_subprocess_exec", _spawn)
    monkeypatch.setattr(olmocr_server, "_terminate_process_group", _terminate)

    with pytest.raises(HTTPException) as exc_info:
        await olmocr_server._run_pipeline(
            request=_Request(disconnected=True),
            workspace=tmp_path,
            input_name="input.pdf",
        )

    assert exc_info.value.status_code == 499
    assert exc_info.value.detail == "client_disconnected"
    assert terminated is True


@pytest.mark.asyncio
async def test_olmocr_convert_returns_markdown_and_cleans_tempdir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    temp_root = tmp_path / "olmocr-temp"
    monkeypatch.setattr(olmocr_server, "_runtime_status", lambda: {"ok": True})
    monkeypatch.setattr(olmocr_server.tempfile, "TemporaryDirectory", lambda **_kwargs: _ManagedTempDir(temp_root))

    async def _run_pipeline(*, workspace: Path, **_kwargs: object) -> tuple[int, str]:
        markdown_dir = workspace / "markdown"
        markdown_dir.mkdir(parents=True, exist_ok=True)
        (markdown_dir / "input.md").write_text("# converted\n", encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(olmocr_server, "_run_pipeline", _run_pipeline)

    result = await olmocr_server.convert(_Request(), _upload_file("scan.pdf", b"%PDF-1.4"))

    assert result == {"markdown": "# converted\n", "output_format": "markdown"}
    assert temp_root.exists() is False


@pytest.mark.asyncio
async def test_olmocr_convert_maps_pipeline_timeout_to_504(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(olmocr_server, "_runtime_status", lambda: {"ok": True})
    monkeypatch.setattr(olmocr_server, "_PIPELINE_TIMEOUT_SEC", 1)

    async def _slow_pipeline(**_kwargs: object) -> tuple[int, str]:
        await asyncio.sleep(0.05)
        return 0, ""

    monkeypatch.setattr(olmocr_server, "_run_pipeline", _slow_pipeline)
    original_wait_for = olmocr_server.asyncio.wait_for

    async def _fast_wait_for(awaitable: Any, timeout: float | None = None) -> Any:
        return await original_wait_for(awaitable, timeout=0.001 if timeout else timeout)

    monkeypatch.setattr(olmocr_server.asyncio, "wait_for", _fast_wait_for)

    with pytest.raises(HTTPException) as exc_info:
        await olmocr_server.convert(_Request(), _upload_file("scan.pdf", b"%PDF-1.4"))

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == "olmocr_pipeline_timeout"


def test_paddlevl_terminate_process_group_escalates_to_sigkill(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakePopen()
    kill_calls: list[tuple[int, signal.Signals]] = []

    monkeypatch.setattr(paddlevl_server.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(paddlevl_server.os, "killpg", lambda pid, sig: kill_calls.append((pid, sig)))

    paddlevl_server._terminate_process_group(proc, grace_sec=0.01)

    assert kill_calls == [(proc.pid, signal.SIGTERM), (proc.pid, signal.SIGKILL)]
    assert proc.returncode == -signal.SIGKILL


def test_paddlevl_run_doc_parser_builds_expected_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    class _SuccessProcess:
        returncode = 0

        def communicate(self, timeout: int) -> tuple[str, str]:
            captured["timeout"] = timeout
            return "ok", ""

    def _popen(cmd: list[str], **kwargs: object) -> _SuccessProcess:
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return _SuccessProcess()

    monkeypatch.setattr(paddlevl_server.subprocess, "Popen", _popen)

    paddlevl_server._run_doc_parser(
        pdf_path=tmp_path / "input.pdf",
        out_dir=tmp_path / "output",
        pipeline_version="v2.0",
        device="gpu:0",
        timeout_sec=42,
    )

    assert captured["cmd"] == [
        "paddleocr",
        "doc_parser",
        "-i",
        str(tmp_path / "input.pdf"),
        "--save_path",
        str(tmp_path / "output"),
        "--pipeline_version",
        "v2.0",
        "--device",
        "gpu:0",
    ]
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert captured["timeout"] == 42


@pytest.mark.asyncio
async def test_paddlevl_convert_returns_zip_and_cleans_tempdir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    temp_root = tmp_path / "paddlevl-temp"
    monkeypatch.setattr(
        paddlevl_server.tempfile,
        "TemporaryDirectory",
        lambda **_kwargs: _ManagedTempDir(temp_root),
    )

    async def _run_in_threadpool(func: Any, **kwargs: object) -> None:
        func(**kwargs)

    def _run_doc_parser(**kwargs: object) -> None:
        out_dir = kwargs["out_dir"]
        assert isinstance(out_dir, Path)
        (out_dir / "result.md").write_text("converted", encoding="utf-8")

    monkeypatch.setattr(paddlevl_server, "run_in_threadpool", _run_in_threadpool)
    monkeypatch.setattr(paddlevl_server, "_run_doc_parser", _run_doc_parser)

    response = await paddlevl_server.convert(_upload_file("scan.pdf", b"%PDF-1.4"))

    with zipfile.ZipFile(io.BytesIO(response.body), "r") as archive:
        assert archive.namelist() == ["result.md"]
        assert archive.read("result.md").decode("utf-8") == "converted"
    assert temp_root.exists() is False


@pytest.mark.asyncio
async def test_paddlevl_convert_maps_timeout_to_504(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run_in_threadpool(_func: Any, **_kwargs: object) -> None:
        raise TimeoutError("doc_parser timed out")

    monkeypatch.setattr(paddlevl_server, "run_in_threadpool", _run_in_threadpool)

    with pytest.raises(HTTPException) as exc_info:
        await paddlevl_server.convert(_upload_file("scan.pdf", b"%PDF-1.4"))

    assert exc_info.value.status_code == 504
    assert "doc_parser timed out" in exc_info.value.detail


def test_qianfan_convert_document_formats_multi_page_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qianfanocr_server, "_PAGE_CONCURRENCY", 2)
    monkeypatch.setattr(qianfanocr_server, "_render_pdf_pages", lambda _data, *, dpi: [b"page-1", b"page-2"])
    monkeypatch.setattr(
        qianfanocr_server,
        "_call_qianfan_ocr",
        lambda *, image_bytes, **_kwargs: image_bytes.decode("utf-8"),
    )

    markdown, page_count = qianfanocr_server._convert_document(b"%PDF-1.4", ".pdf", layout_as_thought=True)

    assert page_count == 2
    assert markdown == "<!-- page 1 -->\npage-1\n\n<!-- page 2 -->\npage-2"


@pytest.mark.asyncio
async def test_qianfan_convert_uses_layout_flag_and_maps_runtime_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def _to_thread(func: Any, *args: object, **kwargs: object) -> Any:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return func(*args, **kwargs)

    def _convert_document(file_bytes: bytes, suffix: str, *, layout_as_thought: bool) -> tuple[str, int]:
        captured["file_bytes"] = file_bytes
        captured["suffix"] = suffix
        captured["layout_as_thought"] = layout_as_thought
        return "markdown", 2

    monkeypatch.setattr(qianfanocr_server.asyncio, "to_thread", _to_thread)
    monkeypatch.setattr(qianfanocr_server, "_convert_document", _convert_document)

    result = await qianfanocr_server.convert(
        _upload_file("scan.pdf", b"%PDF-1.4"),
        layout_as_thought="yes",
    )

    assert result == {
        "markdown": "markdown",
        "output_format": "markdown",
        "pages": 2,
        "layout_as_thought": True,
    }
    assert captured["suffix"] == ".pdf"
    assert captured["layout_as_thought"] is True

    def _raise_runtime_error(*_args: object, **_kwargs: object) -> tuple[str, int]:
        raise RuntimeError("boom")

    monkeypatch.setattr(qianfanocr_server, "_convert_document", _raise_runtime_error)

    with pytest.raises(HTTPException) as exc_info:
        await qianfanocr_server.convert(_upload_file("scan.png", b"png"))

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "qianfan_ocr_error: boom"
