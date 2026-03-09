#!/usr/bin/env python3
import argparse
import json

import torch
import uvicorn
from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoModelForSequenceClassification, AutoTokenizer


class ClassifyRequest(BaseModel):
    text: str | None = None
    texts: list[str] | None = None


class Prediction(BaseModel):
    label: str
    score: float


class ClassifyResponse(BaseModel):
    model: str
    predictions: list[Prediction] | list[list[Prediction]]


parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8003)
parser.add_argument("--model-path", required=True)
parser.add_argument("--max-length", type=int, default=512)
parser.add_argument("--labels-json", default="[]")
parser.add_argument("--return-all-scores", action="store_true")
args = parser.parse_args()

device = "cuda" if torch.cuda.is_available() else "cpu"
labels = json.loads(args.labels_json)
tokenizer = AutoTokenizer.from_pretrained(args.model_path)
model = AutoModelForSequenceClassification.from_pretrained(args.model_path).to(device)
model.eval()

app = FastAPI(title="BERT Classifier API")


def resolve_inputs(payload: ClassifyRequest) -> list[str]:
    if payload.texts:
        return payload.texts
    if payload.text:
        return [payload.text]
    raise HTTPException(status_code=400, detail="Provide text or texts.")


def label_name(index: int) -> str:
    if index < len(labels):
        return labels[index]
    return model.config.id2label.get(index, str(index))


def infer(texts: list[str]) -> list[Prediction] | list[list[Prediction]]:
    encoded = tokenizer(
        texts,
        truncation=True,
        padding=True,
        max_length=args.max_length,
        return_tensors="pt",
    )
    encoded = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode():
        logits = model(**encoded).logits
        scores = torch.softmax(logits, dim=-1).cpu().tolist()

    if args.return_all_scores:
        return [
            [Prediction(label=label_name(i), score=float(score)) for i, score in enumerate(row)]
            for row in scores
        ]

    predictions: list[Prediction] = []
    for row in scores:
        best_index = max(range(len(row)), key=row.__getitem__)
        predictions.append(Prediction(label=label_name(best_index), score=float(row[best_index])))
    return predictions


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/bert/classify", response_model=ClassifyResponse)
def classify(payload: ClassifyRequest = Body(...)) -> ClassifyResponse:
    texts = resolve_inputs(payload)
    if any(not text.strip() for text in texts):
        raise HTTPException(status_code=400, detail="Text inputs must be non-empty.")
    predictions = infer(texts)
    return ClassifyResponse(model=args.model_path, predictions=predictions)


if __name__ == "__main__":
    uvicorn.run(app, host=args.host, port=args.port)
