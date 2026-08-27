from __future__ import annotations

import asyncio
import difflib
import os
import shlex
from pathlib import Path, PurePosixPath

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

WORKSPACE = Path(os.getenv("WORKSPACE_DIR", "/workspace")).resolve()
TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
MAX_OUTPUT = 12000
app = FastAPI(title="Uranus-AI Sandbox", docs_url=None, redoc_url=None)


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


@app.on_event("startup")
async def startup() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)


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
        return {"ok": True, "files": [{"path": str(target.relative_to(WORKSPACE)), "type": "file", "size": target.stat().st_size}]}
    files = []
    for item in sorted(target.rglob("*")):
        if len(files) >= 500:
            break
        if any(part in {".git", "node_modules", "__pycache__"} for part in item.parts):
            continue
        files.append({"path": str(item.relative_to(WORKSPACE)), "type": "dir" if item.is_dir() else "file", "size": item.stat().st_size if item.is_file() else None})
    return {"ok": True, "files": files}


@app.post("/read")
async def read_file(req: FileRequest, _: None = Depends(auth)) -> dict:
    target = safe_path(req.path)
    if not target.is_file():
        return {"ok": False, "error": "File not found"}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "path": str(target.relative_to(WORKSPACE)), "content": text[:req.max_chars], "truncated": len(text) > req.max_chars}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/write")
async def write_file(req: FileRequest, _: None = Depends(auth)) -> dict:
    target = safe_path(req.path)
    if target == WORKSPACE:
        return {"ok": False, "error": "Cannot write workspace root"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding="utf-8")
    return {"ok": True, "path": str(target.relative_to(WORKSPACE)), "bytes": len(req.content.encode())}


@app.post("/delete")
async def delete_file(req: DeleteRequest, _: None = Depends(auth)) -> dict:
    target = safe_path(req.path)
    if target == WORKSPACE:
        return {"ok": False, "error": "Cannot delete workspace root"}
    if target.is_dir():
        try:
            target.rmdir()
        except OSError as exc:
            return {"ok": False, "error": f"Directory is not empty or unavailable: {exc}"}
    elif target.exists():
        target.unlink()
    return {"ok": True, "path": req.path}


@app.post("/patch")
async def patch_files(req: PatchRequest, _: None = Depends(auth)) -> dict:
    # `patch --directory=/workspace` still stays within the mounted workspace.
    process = await asyncio.create_subprocess_exec(
        "patch", "-p1", "--batch", "--forward", "--directory", str(WORKSPACE),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(req.patch.encode())
    return {"ok": process.returncode == 0, "exit_code": process.returncode, "stdout": stdout.decode(errors="replace")[:MAX_OUTPUT], "stderr": stderr.decode(errors="replace")[:MAX_OUTPUT]}
