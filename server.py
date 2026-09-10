"""本地跟读评分：python server.py 或双击 启动.bat"""

from __future__ import annotations

import json
import os
import re
import webbrowser
from difflib import SequenceMatcher
from typing import Any

import requests
from flask import Flask, jsonify, request, send_from_directory

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


def load_config() -> dict[str, str]:
    cfg: dict[str, str] = {}
    path = os.path.join(APP_DIR, "config.txt")
    if not os.path.isfile(path):
        return cfg
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            cfg[key.strip()] = value.strip().strip('"').strip("'")
    return cfg


_cfg = load_config()
ARK_API_KEY = os.environ.get("ARK_API_KEY", _cfg.get("ARK_API_KEY", "")).strip()
ARK_MODEL = os.environ.get("ARK_MODEL", _cfg.get("ARK_MODEL", "")).strip()

app = Flask(__name__, static_folder=APP_DIR, static_url_path="")


def rating_from_overall(score: float) -> str:
    if score >= 85:
        return "优秀"
    if score >= 60:
        return "不错"
    return "再练一次"


def extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("模型返回为空")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"无法解析模型输出: {text[:200]}")
    return json.loads(match.group(0))


def clamp_score(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = default
    return max(0.0, min(100.0, n))


def normalize_text(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9'\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def local_fallback_score(target: str, transcript: str) -> dict[str, Any]:
    t = normalize_text(target)
    u = normalize_text(transcript)
    if not u:
        pronunciation = fluency = completeness = 0.0
    else:
        ratio = SequenceMatcher(None, t, u).ratio()
        tw = set(t.split())
        uw = set(u.split())
        overlap = (len(tw & uw) / len(tw)) if tw else 0.0
        order = SequenceMatcher(None, t.split(), u.split()).ratio() if t and u else 0.0
        pronunciation = 100.0 * (0.55 * ratio + 0.45 * overlap)
        fluency = 100.0 * (0.4 * ratio + 0.6 * order)
        completeness = 100.0 * overlap
    overall = round((pronunciation + fluency + completeness) / 3.0, 1)
    return {
        "pronunciation": round(pronunciation, 1),
        "fluency": round(fluency, 1),
        "completeness": round(completeness, 1),
        "overall": overall,
        "rating": rating_from_overall(overall),
        "comment": "当前为本地兜底评分（未连上豆包）。",
        "transcript": transcript,
        "target": target,
        "source": "local_fallback",
    }


def score_with_doubao(target: str, transcript: str) -> dict[str, Any]:
    system = (
        "英语跟读评分。只输出 JSON："
        '{"pronunciation":0-100,"fluency":0-100,"completeness":0-100,"comment":"一句中文"}'
    )
    user = f"目标：{target}\n识别：{transcript or '（空）'}"
    payload = {
        "model": ARK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 200,
        "thinking": {"type": "disabled"},
    }
    headers = {
        "Authorization": f"Bearer {ARK_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(ARK_URL, headers=headers, json=payload, timeout=90)
    if resp.status_code >= 400 and "thinking" in (resp.text or "").lower():
        payload.pop("thinking", None)
        resp = requests.post(ARK_URL, headers=headers, json=payload, timeout=90)
    if resp.status_code >= 400:
        raise RuntimeError(f"方舟 API 错误 {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    message = data["choices"][0]["message"]
    content = message.get("content") or message.get("reasoning_content") or ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text") or "")
            elif isinstance(item, str):
                parts.append(item)
        content = "\n".join(parts)

    parsed = extract_json(str(content))
    pronunciation = clamp_score(parsed.get("pronunciation"))
    fluency = clamp_score(parsed.get("fluency"))
    completeness = clamp_score(parsed.get("completeness"))
    overall = round((pronunciation + fluency + completeness) / 3.0, 1)
    return {
        "pronunciation": round(pronunciation, 1),
        "fluency": round(fluency, 1),
        "completeness": round(completeness, 1),
        "overall": overall,
        "rating": rating_from_overall(overall),
        "comment": str(parsed.get("comment") or "").strip(),
        "transcript": transcript,
        "target": target,
        "source": "doubao",
    }


@app.get("/")
def index():
    return send_from_directory(APP_DIR, "index.html")


@app.get("/style.css")
def css():
    return send_from_directory(APP_DIR, "style.css")


@app.post("/api/score")
def score():
    body = request.get_json(silent=True) or {}
    target = (body.get("target") or "").strip()
    transcript = (body.get("transcript") or "").strip()
    if not target:
        return jsonify({"error": "缺少目标英文句子"}), 400
    print("score request")
    try:
        data = score_with_doubao(target, transcript)
        print("score ok: doubao")
        return jsonify(data)
    except Exception as exc:
        result = local_fallback_score(target, transcript)
        result["warning"] = str(exc)[:300]
        print("score fallback:", result["warning"])
        return jsonify(result)


if __name__ == "__main__":
    url = "http://127.0.0.1:5050/"
    print("model:", ARK_MODEL)
    print("key:", "yes" if ARK_API_KEY else "no")
    print("open", url, "in Chrome or Edge")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
