from __future__ import annotations

import asyncio
import os
from pathlib import Path, PurePosixPath

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

WORKSPACE = Path(os.getenv("WORKSPACE_DIR", "/workspace")).resolve()
TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
MAX_OUTPUT = 12000
app = FastAPI(title="Uranus-AI Sandbox", docs_url=None, redoc_url=None)


class ExecRequest(BaseModel):
    command: str = Field(min_length=1, max_length=8000)
    timeout: int = Field(default=30, ge=1, le=300)


class FileRequest(BaseModel):
    path: str = Field(default=".", max_length=1000)
    content: str = Field(default="", max_length=500_000)
    max_chars: int = Field(default=20_000, ge=100, le=50_000)


class DeleteRequest(BaseModel):
    path: str = Field(max_length=1000)


class PatchRequest(BaseModel):
    patch: str = Field(min_length=1, max_length=200_000)


class DirectoryRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


def auth(x_internal_token: str | None = Header(default=None)) -> None:
    if not TOKEN or x_internal_token != TOKEN:
        raise HTTPException(status_code=403, detail="Internal token required")


def safe_path(value: str) -> Path:
    raw = str(value or ".").replace("\\", "/")
    rel = PurePosixPath(raw.lstrip("/"))
    if ".." in rel.parts:
        raise HTTPException(status_code=400, detail="Path escapes workspace")
    target = (WORKSPACE / rel).resolve()
    if target != WORKSPACE and WORKSPACE not in target.parents:
        raise HTTPException(status_code=400, detail="Path escapes workspace")
    return target


def display_path(target: Path) -> str:
    return str(target.relative_to(WORKSPACE))


def filesystem_error(operation: str, target: Path, exc: OSError) -> dict[str, object]:
    return {"ok": False, "error": f"{operation} failed for {display_path(target)!r}: {exc.__class__.__name__}: {exc}"}


@app.on_event("startup")
async def startup() -> None:
    try:
        WORKSPACE.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"Cannot initialize workspace {WORKSPACE}: {exc}") from exc


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/exec")
async def execute(req: ExecRequest, _: None = Depends(auth)) -> dict:
    env = {"PATH": os.getenv("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": "/home/uranus", "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1"}
    try:
        process = await asyncio.create_subprocess_exec(
            "/bin/bash", "-lc", req.command,
            cwd=str(WORKSPACE),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=req.timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {"ok": False, "exit_code": 124, "stdout": "", "stderr": f"Команда остановлена по таймауту {req.timeout} сек."}
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        truncated = len(out) > MAX_OUTPUT or len(err) > MAX_OUTPUT
        return {"ok": process.returncode == 0, "exit_code": process.returncode, "stdout": out[:MAX_OUTPUT], "stderr": err[:MAX_OUTPUT], "truncated": truncated}
    except Exception as exc:
        return {"ok": False, "exit_code": 1, "stdout": "", "stderr": str(exc)}


@app.post("/list")
async def list_files(req: FileRequest, _: None = Depends(auth)) -> dict:
    target = safe_path(req.path)
    if not target.exists():
        return {"ok": False, "error": "Path not found"}
    if target.is_file():
        return {"ok": True, "files": [{"path": display_path(target), "type": "file", "size": target.stat().st_size}]}
    files = []
    for item in sorted(target.rglob("*")):
        if len(files) >= 500:
            break
        if any(part in {".git", "node_modules", "__pycache__"} for part in item.parts):
            continue
        files.append({"path": display_path(item), "type": "dir" if item.is_dir() else "file", "size": item.stat().st_size if item.is_file() else None})
    return {"ok": True, "files": files}


@app.post("/read")
async def read_file(req: FileRequest, _: None = Depends(auth)) -> dict:
    target = safe_path(req.path)
    if not target.is_file():
        return {"ok": False, "error": "File not found"}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "path": display_path(target), "content": text[:req.max_chars], "truncated": len(text) > req.max_chars}
    except OSError as exc:
        return filesystem_error("Read", target, exc)


@app.post("/mkdir")
async def make_directory(req: DirectoryRequest, _: None = Depends(auth)) -> dict:
    target = safe_path(req.path)
    if target == WORKSPACE:
        return {"ok": True, "path": ".", "created": False}
    if target.exists():
        if target.is_dir():
            return {"ok": True, "path": display_path(target), "created": False}
        return {"ok": False, "error": f"Cannot create directory {display_path(target)!r}: a file already exists at this path"}
    parent = target.parent
    if parent.exists() and not parent.is_dir():
        return {"ok": False, "error": f"Cannot create directory {display_path(target)!r}: parent {display_path(parent)!r} is a file"}
    try:
        target.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": display_path(target), "created": True}
    except OSError as exc:
        return filesystem_error("Create directory", target, exc)


@app.post("/write")
async def write_file(req: FileRequest, _: None = Depends(auth)) -> dict:
    target = safe_path(req.path)
    if target == WORKSPACE:
        return {"ok": False, "error": "Cannot write workspace root; provide a file path"}
    raw_path = str(req.path or "").replace("\\", "/").rstrip("/")
    if not target.exists() and not req.content and "." not in PurePosixPath(raw_path).name:
        return {"ok": False, "error": f"Path {display_path(target)!r} looks like a directory; use workspace.mkdir before writing files"}
    if target.exists() and target.is_dir():
        return {"ok": False, "error": f"Cannot write {display_path(target)!r}: path is a directory; use a file path"}
    parent = target.parent
    if parent.exists() and not parent.is_dir():
        return {"ok": False, "error": f"Cannot write {display_path(target)!r}: parent {display_path(parent)!r} is a file; create/use a directory path first"}
    try:
        parent.mkdir(parents=True, exist_ok=True)
        target.write_text(req.content, encoding="utf-8")
        return {"ok": True, "path": display_path(target), "bytes": len(req.content.encode())}
    except OSError as exc:
        return filesystem_error("Write", target, exc)


@app.post("/delete")
async def delete_file(req: DeleteRequest, _: None = Depends(auth)) -> dict:
    target = safe_path(req.path)
    if target == WORKSPACE:
        return {"ok": False, "error": "Cannot delete workspace root"}
    try:
        if target.is_dir():
            target.rmdir()
        elif target.exists():
            target.unlink()
        return {"ok": True, "path": req.path}
    except OSError as exc:
        return filesystem_error("Delete", target, exc)


@app.post("/patch")
async def patch_files(req: PatchRequest, _: None = Depends(auth)) -> dict:
    process = await asyncio.create_subprocess_exec(
        "patch", "-p1", "--batch", "--forward", "--directory", str(WORKSPACE),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(req.patch.encode())
    return {"ok": process.returncode == 0, "exit_code": process.returncode, "stdout": stdout.decode(errors="replace")[:MAX_OUTPUT], "stderr": stderr.decode(errors="replace")[:MAX_OUTPUT]}
