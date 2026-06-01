"""REST API routes for the kicad-agent playground.

Endpoints:
    POST /api/upload - Upload a KiCad file
    GET  /api/operations - List available operations
    POST /api/execute - Execute an operation
    POST /api/erc - Run ERC on uploaded file
    POST /api/drc - Run DRC on uploaded file
    GET  /api/preview/{session_id} - SVG preview of uploaded file
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# Allowed extensions
ALLOWED_EXTENSIONS = {".kicad_sch", ".kicad_pcb", ".kicad_sym", ".kicad_mod"}


class ExecuteRequest(BaseModel):
    operation: dict
    session_id: str | None = None


class ErcDrcRequest(BaseModel):
    session_id: str


def _validate_filename(filename: str) -> str:
    """Validate uploaded filename for security.

    Blocks path traversal and non-KiCad extensions.
    """
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filename: path traversal detected",
        )

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {ext!r}. Allowed: {allowed}",
        )

    return filename


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
) -> JSONResponse:
    """Upload a KiCad file for processing."""
    filename = _validate_filename(file.filename or "")

    content = await file.read()
    max_bytes = request.app.state.max_upload_bytes
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {len(content)} bytes (max {max_bytes})",
        )

    session_id = str(uuid.uuid4())
    upload_dir: Path = request.app.state.upload_dir
    ext = Path(filename).suffix
    stored_path = upload_dir / f"{session_id}{ext}"
    stored_path.write_bytes(content)

    request.app.state.sessions[session_id] = {
        "filename": filename,
        "path": str(stored_path),
        "ext": ext,
        "created_at": time.time(),
    }

    return JSONResponse({
        "session_id": session_id,
        "filename": filename,
        "size": len(content),
    })


@router.get("/operations")
async def list_operations() -> JSONResponse:
    """List available operations and their schemas."""
    try:
        from kicad_agent.ops.schema import Operation
        schema = Operation.model_json_schema()
        defs = schema.get("$defs", {})
        op_types = []
        for name, defn in defs.items():
            if "op_type" in defn.get("properties", {}):
                const = defn["properties"]["op_type"].get("const")
                if const:
                    op_types.append({"name": const})
        return JSONResponse(op_types)
    except Exception as exc:
        logger.warning("Failed to list operations: %s", exc)
        return JSONResponse([])


@router.post("/execute")
async def execute_operation(request: Request, body: ExecuteRequest) -> JSONResponse:
    """Execute a kicad-agent operation."""
    from kicad_agent.handler import handle_operation, validate_operation

    op_json = json.dumps(body.operation)

    op, err = validate_operation(op_json)
    if err:
        return JSONResponse(
            status_code=400,
            content={"error": err.error, "suggestion": err.suggestion},
        )

    project_dir = None
    if body.session_id and body.session_id in request.app.state.sessions:
        session = request.app.state.sessions[body.session_id]
        project_dir = Path(session["path"]).parent

    result = handle_operation(op_json, project_dir=project_dir)
    return JSONResponse({"result": asdict(result) if result else None})


@router.post("/erc")
async def run_erc(request: Request, body: ErcDrcRequest) -> JSONResponse:
    """Run ERC on an uploaded schematic."""
    session = request.app.state.sessions.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    sch_path = Path(session["path"])
    if not sch_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        result = subprocess.run(
            ["kicad-cli", "sch", "erc", str(sch_path)],
            capture_output=True, text=True, timeout=120,
        )
        output = result.stdout + result.stderr
        violations = [l for l in output.splitlines() if l.strip()]
        return JSONResponse({
            "violation_count": len(violations),
            "output": output,
            "exit_code": result.returncode,
        })
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="kicad-cli not found")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="ERC timed out")


@router.post("/drc")
async def run_drc(request: Request, body: ErcDrcRequest) -> JSONResponse:
    """Run DRC on an uploaded PCB."""
    session = request.app.state.sessions.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    pcb_path = Path(session["path"])
    if not pcb_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        result = subprocess.run(
            ["kicad-cli", "pcb", "drc", str(pcb_path)],
            capture_output=True, text=True, timeout=120,
        )
        output = result.stdout + result.stderr
        violations = [l for l in output.splitlines() if l.strip()]
        return JSONResponse({
            "violation_count": len(violations),
            "output": output,
            "exit_code": result.returncode,
        })
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="kicad-cli not found")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="DRC timed out")


@router.get("/preview/{session_id}")
async def preview_file(request: Request, session_id: str) -> FileResponse:
    """Get SVG preview of an uploaded file."""
    session = request.app.state.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    file_path = Path(session["path"])
    ext = session.get("ext", "")

    if ext == ".kicad_sch":
        svg_path = file_path.with_suffix(".svg")
        try:
            subprocess.run(
                ["kicad-cli", "sch", "export", "svg", str(file_path), "-o", str(svg_path)],
                capture_output=True, text=True, timeout=120,
            )
            if svg_path.exists():
                return FileResponse(str(svg_path), media_type="image/svg+xml")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        raise HTTPException(status_code=503, detail="SVG export failed")

    raise HTTPException(status_code=400, detail=f"No preview for {ext} files")
