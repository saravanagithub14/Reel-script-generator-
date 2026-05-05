"""
Viral Reel Script Generator — Backend API
FastAPI + Whisper + Multi-Provider LLM (Groq / Ollama / Anthropic)
"""

import os
import json
import uuid
import asyncio
import logging
import re
import httpx
from pathlib import Path
from typing import List, Optional
from datetime import datetime

import yt_dlp
import whisper
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("reel-agent")

# ── Dirs ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
MEDIA_DIR  = BASE_DIR / "media"
MEDIA_DIR.mkdir(exist_ok=True)
STYLE_FILE = BASE_DIR / "style_memory.json"

# ── LLM Provider Config ───────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()   # groq | ollama | anthropic

# Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Ollama
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")

# Whisper
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
_whisper_model     = None   # lazy-loaded

# ── Groq available models (for info endpoint) ─────────────────────────────────
GROQ_MODELS = {
    "llama-3.3-70b-versatile": "Llama 3.3 70B — Best quality",
    "llama3-8b-8192":          "Llama 3 8B — Fastest",
    "mixtral-8x7b-32768":      "Mixtral 8x7B — Long context",
    "gemma2-9b-it":            "Gemma 2 9B — Lightweight",
    "llama-3.1-8b-instant":    "Llama 3.1 8B Instant",
}

# ═══════════════════════════════════════════════════════════════════════════════
# LLM PROVIDER ABSTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

async def call_llm(system: str, user: str, provider: str = None) -> tuple[str, str]:
    """
    Unified LLM call — returns (response_text, model_label).
    Falls back through: groq → ollama → anthropic if primary fails.
    """
    provider = provider or LLM_PROVIDER

    if provider == "groq":
        return await _call_groq(system, user)
    elif provider == "ollama":
        return await _call_ollama(system, user)
    elif provider == "anthropic":
        return await _call_anthropic(system, user)
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def _call_groq(system: str, user: str) -> tuple[str, str]:
    """Groq — OpenAI-compatible REST API, free tier."""
    if not GROQ_API_KEY:
        raise HTTPException(500, "GROQ_API_KEY not set. Get a free key at console.groq.com")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": 2048,
        "temperature": 0.85,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
        )

    if resp.status_code != 200:
        err = resp.json().get("error", {}).get("message", resp.text)
        raise HTTPException(502, f"Groq error: {err}")

    data  = resp.json()
    text  = data["choices"][0]["message"]["content"]
    model = data.get("model", GROQ_MODEL)
    return text, f"Groq · {model}"


async def _call_ollama(system: str, user: str) -> tuple[str, str]:
    """Ollama — fully local, no API key needed."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.85, "num_predict": 2048},
    }

    async with httpx.AsyncClient(timeout=300) as client:
        try:
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
            )
        except httpx.ConnectError:
            raise HTTPException(
                503,
                f"Ollama not running at {OLLAMA_BASE_URL}. "
                "Install from ollama.ai and run: ollama serve"
            )

    if resp.status_code != 200:
        raise HTTPException(502, f"Ollama error: {resp.text}")

    data = resp.json()
    text = data["message"]["content"]
    return text, f"Ollama · {OLLAMA_MODEL}"


async def _call_anthropic(system: str, user: str) -> tuple[str, str]:
    """Anthropic Claude — paid, optional."""
    try:
        import anthropic as _ant
    except ImportError:
        raise HTTPException(500, "anthropic package not installed. Run: pip install anthropic")

    if not ANTHROPIC_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY not set in backend/.env")

    client  = _ant.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = message.content[0].text
    return text, f"Anthropic · {ANTHROPIC_MODEL}"


def provider_ready() -> bool:
    """Quick check if the configured provider can be used."""
    if LLM_PROVIDER == "groq":
        return bool(GROQ_API_KEY)
    if LLM_PROVIDER == "ollama":
        return True   # always attempt; error surfaces on actual call
    if LLM_PROVIDER == "anthropic":
        return bool(ANTHROPIC_API_KEY)
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# WHISPER
# ═══════════════════════════════════════════════════════════════════════════════

def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        log.info(f"Loading Whisper model: {WHISPER_MODEL_NAME}")
        _whisper_model = whisper.load_model(WHISPER_MODEL_NAME)
    return _whisper_model


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE MEMORY
# ═══════════════════════════════════════════════════════════════════════════════

def load_style_memory() -> dict:
    if STYLE_FILE.exists():
        with open(STYLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"transcripts": []}

def save_style_memory(mem: dict):
    with open(STYLE_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# JOB TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

jobs: dict[str, dict] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Viral Reel Script Generator", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND_DIR = BASE_DIR.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")


# ── Pydantic Models ───────────────────────────────────────────────────────────

class LinkRequest(BaseModel):
    urls: List[str]

class ScriptRequest(BaseModel):
    topic:        str
    is_paragraph: bool = False
    provider:     Optional[str] = None   # override env default per-request

class ProviderSwitchRequest(BaseModel):
    provider: str   # groq | ollama | anthropic
    model:    Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# DOWNLOAD & TRANSCRIBE
# ═══════════════════════════════════════════════════════════════════════════════

def sanitize_filename(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", s)[:80]

async def download_and_transcribe(job_id: str, urls: List[str]):
    jobs[job_id]["status"] = "running"
    results = []

    for idx, url in enumerate(urls):
        prefix = f"[{idx+1}/{len(urls)}]"
        jobs[job_id]["progress"] = f"{prefix} Downloading..."

        try:
            vid_id   = str(uuid.uuid4())[:8]
            out_tmpl = str(MEDIA_DIR / f"{vid_id}_%(title)s.%(ext)s")

            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": out_tmpl,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }],
                "quiet": True,
                "no_warnings": True,
            }

            loop            = asyncio.get_event_loop()
            downloaded_path = None
            video_title     = "Unknown"

            def _do_download():
                nonlocal downloaded_path, video_title
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    video_title = info.get("title", "Unknown")
                    for f in MEDIA_DIR.glob(f"{vid_id}*"):
                        if f.suffix in (".mp3", ".m4a", ".wav", ".ogg", ".opus"):
                            downloaded_path = str(f)
                            return
                    # fallback: any file with that id
                    for f in MEDIA_DIR.glob(f"{vid_id}*"):
                        downloaded_path = str(f)
                        return

            await loop.run_in_executor(None, _do_download)

            if not downloaded_path:
                raise FileNotFoundError("Audio file not found after download.")

            jobs[job_id]["progress"] = f"{prefix} Transcribing with Whisper..."
            log.info(f"Transcribing: {downloaded_path}")

            def _do_transcribe():
                return get_whisper().transcribe(downloaded_path, task="transcribe")

            result          = await loop.run_in_executor(None, _do_transcribe)
            transcript_text = result.get("text", "").strip()

            mem = load_style_memory()
            mem["transcripts"].append({
                "source":     url,
                "title":      video_title,
                "transcript": transcript_text,
                "added_at":   datetime.utcnow().isoformat(),
            })
            save_style_memory(mem)

            results.append({"url": url, "title": video_title, "transcript": transcript_text, "status": "success"})

            try:
                os.remove(downloaded_path)
            except Exception:
                pass

        except Exception as e:
            log.error(f"Error processing {url}: {e}")
            results.append({"url": url, "status": "error", "error": str(e)})

    jobs[job_id].update({"status": "done", "progress": "Complete", "result": results})


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def build_system_prompt(transcripts: list) -> str:
    if not transcripts:
        style_section = (
            "No example reels available yet — use a natural, casual Malayalam "
            "creator voice mixed with English tech terms."
        )
    else:
        examples = "\n\n---\n\n".join(
            f"EXAMPLE {i+1} ({t.get('title','')}):\n{t['transcript']}"
            for i, t in enumerate(transcripts)
        )
        style_section = (
            "You have been trained on the following real reel transcripts from this creator.\n"
            "Study the exact style, sentence length, Malayalam-English mix, emotional tone, "
            "and CTA patterns. Always match this creator's voice precisely.\n\n"
            f"{examples}"
        )

    return f"""You are an expert viral Malayalam tech reel scriptwriter.

{style_section}

VIRAL REEL FRAMEWORK — ALWAYS FOLLOW THIS STRUCTURE:
1. HOOK (0–3 sec): Personal story or relatable pain point. First person. Stops the scroll.
2. PROBLEM (3–7 sec): State the knowledge gap. Why does this matter?
3. VALUE (7–25 sec): MAX 3 points. Each: name + one-line explanation + real-life example.
4. CLOSER (25–28 sec): One bold, slightly controversial statement. Creates FOMO/debate.
5. CTA (28–30 sec): Give a reason to follow, not just an ask.

LANGUAGE RULES:
- Casual spoken Malayalam throughout
- All technical terms stay in English
- Short, punchy sentences
- Never exceed 3 value points
- End the CTA with 🔥

VIRAL SCORE TARGETS (each out of 20):
- Hook Strength ≥ 17
- Relatability ≥ 17
- Information Density ≥ 16
- Language Style Match ≥ 18
- CTA Effectiveness ≥ 17
- Emotional Pull ≥ 17
- Share Trigger ≥ 17
Total target: ≥ 95/140

After writing the script output:
1. The script with Malayalam text and timestamps
2. Viral score breakdown (each factor /20, total /140)
3. One-line fact-check note per factual claim
"""

def build_user_prompt(topic: str, is_paragraph: bool) -> str:
    if is_paragraph:
        return f"""Here is my research / source material:

{topic}

Based on this material:
1. Identify the 3 most important points
2. Find a relatable hook story from this content
3. Write the complete 30-second viral reel script following the framework
4. Score it and fact-check every claim

Output the final publish-ready script with timestamps."""
    else:
        return f"""Topic: {topic}

Write a complete 30-second viral reel script on this topic for a Malayalam tech audience \
(age 18–35, Kerala — students, freelancers, early-career tech workers).

First research the best angle:
- Most relatable pain point this audience has felt personally
- Most surprising or counterintuitive fact about this topic
- Best real-life example this audience will immediately understand
- One bold statement that sparks comment debate

Then write the full script with timestamps, viral score breakdown, and fact-check notes."""


# ═══════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "ViralCraft AI API — frontend not found"}


@app.get("/api/health")
async def health():
    """Returns current provider status, configured model, and style transcript count."""
    provider_info = {
        "groq":      {"configured": bool(GROQ_API_KEY),      "model": GROQ_MODEL,      "free": True},
        "ollama":    {"configured": True,                     "model": OLLAMA_MODEL,    "free": True,  "local": True},
        "anthropic": {"configured": bool(ANTHROPIC_API_KEY), "model": ANTHROPIC_MODEL, "free": False},
    }
    return {
        "status":            "ok",
        "active_provider":   LLM_PROVIDER,
        "provider_ready":    provider_ready(),
        "providers":         provider_info,
        "groq_models":       GROQ_MODELS,
        "whisper_model":     WHISPER_MODEL_NAME,
        "style_transcripts": len(load_style_memory().get("transcripts", [])),
    }


@app.get("/api/providers")
async def list_providers():
    return {
        "active": LLM_PROVIDER,
        "available": [
            {"id": "groq",      "name": "Groq",      "free": True,  "local": False, "ready": bool(GROQ_API_KEY),      "model": GROQ_MODEL,      "description": "Free API · Llama 3 / Mixtral · Fast"},
            {"id": "ollama",    "name": "Ollama",     "free": True,  "local": True,  "ready": True,                    "model": OLLAMA_MODEL,    "description": "Fully local · No internet needed · Private"},
            {"id": "anthropic", "name": "Anthropic",  "free": False, "local": False, "ready": bool(ANTHROPIC_API_KEY), "model": ANTHROPIC_MODEL, "description": "Claude · Paid · Best quality"},
        ],
        "groq_models": list(GROQ_MODELS.keys()),
    }


@app.post("/api/download")
async def start_download(req: LinkRequest, bg: BackgroundTasks):
    if not req.urls:
        raise HTTPException(400, "No URLs provided")
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "progress": "Queued...", "result": None, "error": None}
    bg.add_task(download_and_transcribe, job_id, req.urls)
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


@app.get("/api/style-memory")
async def get_style_memory():
    mem = load_style_memory()
    summaries = [
        {
            "index":    i,
            "title":    t.get("title", "Untitled"),
            "source":   t.get("source", ""),
            "preview":  t["transcript"][:200] + ("..." if len(t["transcript"]) > 200 else ""),
            "length":   len(t["transcript"]),
            "added_at": t.get("added_at", ""),
        }
        for i, t in enumerate(mem.get("transcripts", []))
    ]
    return {"count": len(summaries), "transcripts": summaries}


@app.delete("/api/style-memory/{index}")
async def delete_transcript(index: int):
    mem = load_style_memory()
    ts  = mem.get("transcripts", [])
    if index < 0 or index >= len(ts):
        raise HTTPException(400, "Invalid index")
    removed = ts.pop(index)
    mem["transcripts"] = ts
    save_style_memory(mem)
    return {"message": f"Removed: {removed.get('title', 'Untitled')}"}


@app.delete("/api/style-memory")
async def clear_style_memory():
    save_style_memory({"transcripts": []})
    return {"message": "Style memory cleared"}


@app.post("/api/generate-script")
async def generate_script(req: ScriptRequest):
    if not provider_ready() and (req.provider or LLM_PROVIDER) != "ollama":
        prov = req.provider or LLM_PROVIDER
        raise HTTPException(
            500,
            f"Provider '{prov}' not configured. "
            "Check your API key in backend/.env and restart the server."
        )

    mem         = load_style_memory()
    transcripts = mem.get("transcripts", [])
    system      = build_system_prompt(transcripts)
    user        = build_user_prompt(req.topic, req.is_paragraph)

    prov = req.provider or LLM_PROVIDER
    log.info(f"Generating via {prov} | style: {len(transcripts)} reels | topic: {req.topic[:60]}")

    script_text, model_label = await call_llm(system, user, provider=prov)

    return {
        "script":              script_text,
        "style_examples_used": len(transcripts),
        "model":               model_label,
        "provider":            prov,
    }
