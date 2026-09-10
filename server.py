"""
talk_talk 后端：接收跟读识别文本，调用火山方舟豆包 Seed 评分。
启动：python server.py
"""

from __future__ import annotations

import json
import os
import re
import traceback
from difflib import SequenceMatcher
from typing import Any

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

APP_DIR = os.path.dirname(os.path.abspath(__file__))

ARK_API_KEY = os.environ.get("ARK_API_KEY", "").strip()
ARK_MODEL = os.environ.get("ARK_MODEL", "doubao-seed-1-8-251228").strip()
ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

app = Flask(__name__, static_folder=APP_DIR, static_url_path="")
CORS(app)


@app.errorhandler(500)
def handle_500(err):
    print("500:", traceback.format_exc())
    return jsonify({"error": str(err) or "Internal Server Error"}), 500


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
    """模型未开通时的文本相似度兜底，保证演示链路可跑通。"""
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
        "comment": "当前使用本地兜底评分。请到方舟控制台开通豆包 Seed，并设置 ARK_MODEL 为已开通的模型 ID 或 ep 接入点。",
        "transcript": transcript,
        "target": target,
        "source": "local_fallback",
    }


def score_with_doubao(target: str, transcript: str) -> dict[str, Any]:
    system = (
        "你是英语口语跟读教练。根据「目标英文」和「用户识别文本」，"
        "从发音准确度、流利度、完整度三个维度打 0-100 分。"
        "只能输出一个 JSON 对象，不要其它说明文字。"
        "字段：pronunciation, fluency, completeness, comment。"
        "comment 用简短中文，指出主要问题或肯定优点。"
    )
    user = (
        f"目标英文：{target}\n"
        f"用户朗读识别结果：{transcript or '（未识别到有效语音）'}\n\n"
        "评分参考：\n"
        "- pronunciation：单词是否接近目标、拼写/用词是否正确\n"
        "- fluency：是否顺畅、有无明显卡顿或乱序（仅根据文本推断）\n"
        "- completeness：是否覆盖目标句主要信息，有无严重漏读\n"
        "若几乎没读出内容，三项都给低分。"
    )

    payload = {
        "model": ARK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 300,
    }
    headers = {
        "Authorization": f"Bearer {ARK_API_KEY}",
        "Content-Type": "application/json",
    }

    # 控制在 gunicorn/平台超时之前结束，避免 WORKER TIMEOUT → HTML 500
    resp = requests.post(ARK_URL, headers=headers, json=payload, timeout=25)
    if resp.status_code >= 400:
        raise RuntimeError(f"方舟 API 错误 {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"方舟返回结构异常: {json.dumps(data, ensure_ascii=False)[:500]}") from exc

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
    comment = str(parsed.get("comment") or "").strip()

    return {
        "pronunciation": round(pronunciation, 1),
        "fluency": round(fluency, 1),
        "completeness": round(completeness, 1),
        "overall": overall,
        "rating": rating_from_overall(overall),
        "comment": comment,
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


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "model": ARK_MODEL})


@app.post("/api/score")
def score():
    body = request.get_json(silent=True) or {}
    target = (body.get("target") or "").strip()
    transcript = (body.get("transcript") or "").strip()

    if not target:
        return jsonify({"error": "缺少目标英文句子 target"}), 400

    if not ARK_API_KEY:
        result = local_fallback_score(target, transcript)
        result["warning"] = "未设置 ARK_API_KEY，使用本地兜底评分"
        return jsonify(result)

    try:
        result = score_with_doubao(target, transcript)
        return jsonify(result)
    except Exception as exc:
        msg = str(exc)
        print("score error:", msg)
        print(traceback.format_exc())
        # 未开通 / 找不到 / 超时：本地兜底，避免前端收到 HTML 500
        soft = (
            "ModelNotOpen" in msg
            or "InvalidEndpointOrModel" in msg
            or "NotFound" in msg
            or "timed out" in msg.lower()
            or "timeout" in msg.lower()
            or isinstance(exc, (requests.Timeout, requests.ConnectionError))
        )
        if soft:
            result = local_fallback_score(target, transcript)
            result["warning"] = msg[:300]
            return jsonify(result)
        return jsonify({"error": msg}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"talk_talk 后端已启动，模型: {ARK_MODEL}，端口: {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
