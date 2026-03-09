#!/usr/bin/env python3
import argparse
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from faster_whisper import WhisperModel


parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8002)
parser.add_argument("--model-path", required=True)
parser.add_argument("--compute-type", default="float16")
parser.add_argument("--beam-size", type=int, default=5)
parser.add_argument("--vad-filter", action="store_true")
args = parser.parse_args()

app = FastAPI(title="Whisper API")
model = WhisperModel(args.model_path, device="cuda", compute_type=args.compute_type)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model_name: str = Form(default="whisper-1"),
    language: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    temperature: float = Form(default=0.0),
) -> dict:
    suffix = Path(file.filename or "audio").suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        tmp.write(content)
        tmp_path = tmp.name

    segments, info = model.transcribe(
        tmp_path,
        beam_size=args.beam_size,
        language=language,
        initial_prompt=prompt,
        temperature=temperature,
        vad_filter=args.vad_filter,
    )
    text = "".join(segment.text for segment in segments).strip()
    return {
        "text": text,
        "model": model_name,
        "language": info.language,
        "duration": info.duration,
    }


if __name__ == "__main__":
    uvicorn.run(app, host=args.host, port=args.port)
