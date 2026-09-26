from __future__ import annotations

import asyncio
import base64
import os
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import diagrams
from . import structural_engine as eng
from .gemini_client import SYSTEM_PROMPTS
from .image_gen import ImageGenError, generate_image
from .pdf_parser import parse_pdf
from .session_store import store

app = FastAPI(title="CivilBot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cap concurrent in-flight Gemini calls so a free-tier rate limit degrades
# gracefully (queued requests) instead of every request erroring at once.
_MAX_CONCURRENT_CHATS = int(os.environ.get("MAX_CONCURRENT_CHATS", "5"))
_chat_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CHATS)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    mode: str = "general"


class ChatImage(BaseModel):
    data_url: str
    caption: str | None = None


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[dict]
    images: list[ChatImage] = []
    session_id: str


@app.get("/api/health")
def health():
    return {"status": "ok", "gemini_key_set": bool(os.environ.get("GEMINI_API_KEY"))}


@app.get("/api/modes")
def modes():
    return {"modes": list(SYSTEM_PROMPTS.keys())}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if req.mode not in SYSTEM_PROMPTS:
        raise HTTPException(400, f"Unknown mode '{req.mode}', expected one of {list(SYSTEM_PROMPTS)}")
    if not req.message.strip():
        raise HTTPException(400, "message must not be empty")

    session_id = req.session_id or str(uuid.uuid4())

    async with _chat_semaphore:
        state = store.get_chat_session(session_id, req.mode)
        message = req.message
        if state.pdf_context:
            message = f"{state.pdf_context}\n\nUser question: {req.message}"
            state.pdf_context = None  # only inject once per upload
        try:
            reply, tool_calls, raw_images = await asyncio.to_thread(state.chat_session.send, message)
        except RuntimeError as e:
            raise HTTPException(500, str(e))
        except Exception as e:
            raise HTTPException(502, f"Chat backend error: {e}")

    images = [
        ChatImage(data_url=f"data:{img['mime']};base64,{base64.b64encode(img['data']).decode()}", caption=img.get("caption"))
        for img in raw_images
    ]
    return ChatResponse(reply=reply, tool_calls=tool_calls, images=images, session_id=session_id)


@app.post("/api/upload-pdf")
async def upload_pdf(session_id: str, file: UploadFile = File(...)):
    if file.content_type != "application/pdf" and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")
    content = await file.read()
    max_bytes = 15 * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(413, "PDF too large (15MB limit on the free tier)")

    try:
        result = parse_pdf(content, file.filename)
    except Exception as e:
        raise HTTPException(422, f"Could not parse PDF: {e}")

    quantities_desc = ", ".join(
        f"{q.label}={q.value:.4g}{'' if q.unit == 'grade' else ' (SI)'} [from: \"{q.raw_match}\"]"
        for q in result.quantities
    ) or "none confidently detected"

    context = (
        f"The user uploaded a document '{result.filename}' ({result.page_count} pages, "
        f"{result.tables_found} tables detected). Heuristically extracted quantities: {quantities_desc}. "
        "Extraction is regex-based and can be wrong or incomplete - confirm any value with the user "
        "before using it in a calculation tool call. Document excerpt follows:\n"
        f"---\n{result.text_excerpt}\n---"
    )
    store.set_pdf_context(session_id, context)

    return {
        "filename": result.filename,
        "page_count": result.page_count,
        "tables_found": result.tables_found,
        "quantities": [q.model_dump() for q in result.quantities],
    }


@app.post("/api/calc/beam", response_model=eng.BeamResult)
def calc_beam(inp: eng.BeamInput):
    try:
        return eng.analyze_beam(inp)
    except eng.EngineError as e:
        raise HTTPException(422, str(e))


@app.post("/api/calc/truss", response_model=eng.TrussResult)
def calc_truss(inp: eng.TrussInput):
    try:
        return eng.analyze_truss(inp)
    except eng.EngineError as e:
        raise HTTPException(422, str(e))


@app.post("/api/calc/column", response_model=eng.ColumnResult)
def calc_column(inp: eng.ColumnInput):
    try:
        return eng.analyze_column(inp)
    except eng.EngineError as e:
        raise HTTPException(422, str(e))


@app.post("/api/calc/beam/diagram")
def calc_beam_diagram(inp: eng.BeamInput):
    try:
        result = eng.analyze_beam(inp)
        png = diagrams.beam_diagram_png(inp, result)
    except eng.EngineError as e:
        raise HTTPException(422, str(e))
    return Response(content=png, media_type="image/png")


@app.post("/api/calc/truss/diagram")
def calc_truss_diagram(inp: eng.TrussInput):
    try:
        result = eng.analyze_truss(inp)
        png = diagrams.truss_diagram_png(inp, result)
    except eng.EngineError as e:
        raise HTTPException(422, str(e))
    return Response(content=png, media_type="image/png")


class ImageRequest(BaseModel):
    prompt: str
    width: int = 768
    height: int = 512


@app.post("/api/generate-image")
def api_generate_image(req: ImageRequest):
    try:
        data = generate_image(req.prompt, req.width, req.height)
    except ImageGenError as e:
        raise HTTPException(422, str(e))
    return Response(content=data, media_type="image/jpeg")


_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
