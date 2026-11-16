"""Helpers for cleaning raw model output."""
import json
import re

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def strip_think(text: str) -> str:
    """Remove Qwen-style <think>…</think> reasoning blocks."""
    return _THINK.sub("", text).strip()


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (handles fences and chatter)."""
    text = strip_think(text)
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model reply")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON reply is not an object")
    return data