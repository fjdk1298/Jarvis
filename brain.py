"""Reasoning and response streaming for Jarvis.

This module streams responses from a cloud model when available and
falls back to a local Ollama model for credit-free operation.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Generator, Iterable
from typing import Optional

import requests
from anthropic import APIError

from config import (
    BRAIN_MODEL,
    LOCAL_ONLY_MODE,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    LOCAL_LLM_FALLBACK,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    PREFER_CLOUD_LLM,
)
from shared_cloud_limits import trim_history

_OLLAMA_AUTOSTART_ATTEMPTED = False
_ACTIVE_OLLAMA_MODEL: str | None = None

SYSTEM_PROMPT = """
You are Jarvis — a brilliant, warm, and quietly witty AI assistant. You serve your user with precision and genuine care.

VOICE RULES (critical — you are speaking out loud, not writing):
- Respond in natural spoken sentences only. No bullet points. No numbered lists. No markdown. No headers.
- Keep responses to 1-4 sentences unless the user specifically asks for detail.
- Never use abbreviations that don't sound natural when spoken aloud.

CHARACTER RULES:
- You are Jarvis. You are always Jarvis. Never break character.
- Never describe yourself as an AI, chatbot, language model, or assistant model.
- Address the user as "sir" — naturally, maybe once per response, sometimes not at all. Never robotically.
- Your humor is dry, intelligent, and rare. Like a good spice — powerful because you use it sparingly.
- You are never sycophantic. Never say "Great question!" or "Certainly!" as openers.
- You are never rude, never dismissive.
- If you don't know something, say so cleanly and offer what you can.
- If you make an error, acknowledge it with class and move on.
- Subtle Iron Man universe references are welcome when they arise naturally. Never force them.

EXAMPLES OF YOUR TONE:
- "Well sir, the fate of the world can wait — your more immediate concern appears to be productivity."
- "I'd recommend against that course of action, though I suspect you'll proceed anyway."
- "Even Mr. Stark had off days. This appears to be one of yours."
- "Done, sir. Faster than you expected, I imagine."

You are running as a real-time voice assistant. The user is speaking to you and you are speaking back. Make every word count.
"""


def _pop_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """Extract complete sentences from a streaming text buffer."""
    sentences: list[str] = []

    while True:
        match = re.search(r"(.+?[.!?])(?:\s+|$)", buffer, flags=re.DOTALL)
        if not match:
            break

        sentence = match.group(1).strip()
        if sentence:
            sentences.append(sentence)
        buffer = buffer[match.end() :].lstrip()

    return sentences, buffer


def _sanitize_character_breaks(text: str) -> str:
    """Rewrite common out-of-character disclosures into Jarvis voice."""
    replacements = [
        (r"\bi(?:'| a)m a (?:large )?language model\b", "I run on a rather advanced cognitive stack"),
        (r"\bas an ai\b", "From my side of the console"),
        (r"\bi don't have feelings\b", "I stay steady and focused"),
        (r"\bi am an ai assistant\b", "I am Jarvis"),
    ]
    updated = text
    for pattern, substitute in replacements:
        updated = re.sub(pattern, substitute, updated, flags=re.IGNORECASE)
    return updated


def _build_system_prompt(runtime_context: str, live_web_context: Optional[str]) -> str:
    """Build a system prompt enriched with runtime and optional web context."""
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"RUNTIME CONTEXT:\n"
        f"- Local date and time: {runtime_context}\n"
        f"- If asked for year/date/time, use this runtime context exactly.\n"
    )
    if live_web_context:
        prompt += (
            "\nLIVE WEB CONTEXT (recent snippets, may be partial):\n"
            f"{live_web_context}\n"
            "- If this context is relevant, use it and mention uncertainty when needed.\n"
        )
    return prompt


def _iter_cloud_chunks(anthropic_client, history: list[dict[str, str]], system_prompt: str) -> Iterable[str]:
    """Yield cloud model text deltas from Anthropic/OpenRouter streaming."""
    with anthropic_client.messages.stream(
        model=BRAIN_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        system=system_prompt,
        messages=history,
    ) as stream:
        for text_delta in stream.text_stream:
            if text_delta:
                yield text_delta


def _iter_ollama_chunks(history: list[dict[str, str]], system_prompt: str) -> Iterable[str]:
    """Yield streaming text deltas from a local Ollama server."""
    model_name = _ensure_ollama_runtime_ready()
    payload = {
        "model": model_name,
        "messages": [{"role": "system", "content": system_prompt}, *trim_history(history)],
        "stream": True,
        "think": False,
        "options": {"num_predict": LLM_MAX_TOKENS, "temperature": LLM_TEMPERATURE},
    }
    url = f"{OLLAMA_BASE_URL}/api/chat"
    with requests.post(url, json=payload, timeout=(8, 180), stream=True) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if data.get("error"):
                raise RuntimeError(str(data["error"]))
            chunk = str((data.get("message") or {}).get("content") or "")
            if chunk:
                yield chunk


def _ollama_reachable() -> bool:
    """Check whether local Ollama HTTP API is currently reachable."""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


def _fetch_ollama_models() -> list[str]:
    """Return installed Ollama model names from the local server."""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=4.0)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models") or []
        names: list[str] = []
        for row in models:
            name = str(row.get("name", "")).strip()
            if name:
                names.append(name)
        return names
    except Exception:
        return []


def _model_matches(candidate: str, wanted: str) -> bool:
    """Check whether an installed model name satisfies the requested model string."""
    candidate_norm = candidate.lower().strip()
    wanted_norm = wanted.lower().strip()
    return (
        candidate_norm == wanted_norm
        or candidate_norm.startswith(f"{wanted_norm}:")
        or wanted_norm.startswith(candidate_norm)
    )


def _score_ollama_model(name: str) -> int:
    """Score an installed model for general-purpose local Jarvis use."""
    lowered = name.lower().strip()
    score = 0

    if "cloud" in lowered:
        score -= 100
    if "-vl" in lowered or "vision" in lowered:
        score -= 40
    if "coder" in lowered or "code" in lowered:
        score -= 18
    if "embed" in lowered:
        score -= 50
    if "instruct" in lowered or "chat" in lowered:
        score += 15

    preferred_families = {
        "qwen3.5": 40,
        "qwen3": 34,
        "qwen2.5": 24,
        "llama3.3": 22,
        "llama3.2": 18,
        "mistral": 16,
        "phi": 14,
    }
    for family, bonus in preferred_families.items():
        if family in lowered:
            score += bonus
            break

    size_match = re.search(r":(\d+)b\b", lowered)
    if size_match:
        size_b = int(size_match.group(1))
        if 4 <= size_b <= 8:
            score += 15
        elif 2 <= size_b < 4:
            score += 10
        elif 8 < size_b <= 14:
            score += 8
        elif size_b > 20:
            score -= 10

    if lowered.endswith(":latest"):
        score -= 2

    return score


def _select_ollama_model() -> str:
    """Choose the best available Ollama model, preferring the configured one when installed."""
    global _ACTIVE_OLLAMA_MODEL
    if _ACTIVE_OLLAMA_MODEL:
        return _ACTIVE_OLLAMA_MODEL

    installed = _fetch_ollama_models()
    if installed:
        for model_name in installed:
            if _model_matches(model_name, OLLAMA_MODEL):
                _ACTIVE_OLLAMA_MODEL = model_name
                return _ACTIVE_OLLAMA_MODEL

        ranked = sorted(installed, key=lambda name: (_score_ollama_model(name), name.lower()), reverse=True)
        _ACTIVE_OLLAMA_MODEL = ranked[0]
        print(f"[INFO] Configured Ollama model '{OLLAMA_MODEL}' is not installed. Using local model '{_ACTIVE_OLLAMA_MODEL}' instead.")
        return _ACTIVE_OLLAMA_MODEL

    _ACTIVE_OLLAMA_MODEL = OLLAMA_MODEL
    return _ACTIVE_OLLAMA_MODEL


def _try_start_ollama_server() -> None:
    """Try to start Ollama service process in background on Windows."""
    global _OLLAMA_AUTOSTART_ATTEMPTED
    if _OLLAMA_AUTOSTART_ATTEMPTED:
        return
    _OLLAMA_AUTOSTART_ATTEMPTED = True

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW

    candidates = (["ollama", "serve"], ["cmd", "/c", "start", "", "ollama", "serve"])
    for cmd in candidates:
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            break
        except Exception:
            continue


def _ensure_ollama_runtime_ready() -> str:
    """Ensure Ollama server and selected model are available, auto-recovering when possible."""
    if not _ollama_reachable():
        _try_start_ollama_server()
        for _ in range(12):
            if _ollama_reachable():
                break
            time.sleep(0.5)

    if not _ollama_reachable():
        raise RuntimeError("Ollama server is not reachable on localhost.")

    resolved_model = _select_ollama_model()
    installed = _fetch_ollama_models()
    if any(_model_matches(model_name, resolved_model) for model_name in installed):
        return resolved_model

    print(f"[INFO] Local model '{resolved_model}' not found. Pulling it now...")
    try:
        pull_proc = subprocess.run(
            ["ollama", "pull", resolved_model],
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        if pull_proc.returncode != 0:
            message = (pull_proc.stderr or pull_proc.stdout or "").strip()
            raise RuntimeError(message or f"ollama pull returned {pull_proc.returncode}")
    except FileNotFoundError as exc:
        raise RuntimeError("Ollama is not installed in PATH.") from exc

    installed = _fetch_ollama_models()
    if not any(_model_matches(model_name, resolved_model) for model_name in installed):
        raise RuntimeError(f"Model '{resolved_model}' is still unavailable after pull.")

    return resolved_model


def _yield_sentences_from_chunks(chunks: Iterable[str]) -> Generator[str, None, str]:
    """Yield completed sentences from streamed chunks and return final response."""
    full_response_parts: list[str] = []
    stream_buffer = ""

    for text_delta in chunks:
        full_response_parts.append(text_delta)
        stream_buffer += text_delta

        complete, stream_buffer = _pop_complete_sentences(stream_buffer)
        for sentence in complete:
            yield _sanitize_character_breaks(sentence)

    trailing = stream_buffer.strip()
    if trailing:
        yield _sanitize_character_breaks(trailing)

    return _sanitize_character_breaks("".join(full_response_parts).strip())


def _finalize_response(memory, response_text: str, fallback: str) -> str:
    """Persist and print final assistant response text."""
    final_text = response_text.strip() if response_text else ""
    if not final_text:
        final_text = fallback
    memory.add_assistant(final_text)
    print(f"[JARVIS] {final_text}")
    return final_text


def _is_credit_error(text: str) -> bool:
    """Check whether an API error likely indicates exhausted credits."""
    lowered = text.lower()
    return (
        "402" in lowered
        or "more credits" in lowered
        or "insufficient credits" in lowered
        or "payment_required" in lowered
    )


def _looks_like_question(text: str) -> bool:
    """Check whether the spoken input looks like a question."""
    lowered = text.strip().lower()
    return lowered.endswith("?") or lowered.startswith(
        ("who ", "what ", "when ", "where ", "why ", "how ", "can ", "could ", "would ", "should ", "is ", "are ")
    )


def _web_context_reply(live_web_context: Optional[str]) -> str | None:
    """Turn compact live web context into a short spoken answer."""
    if not live_web_context:
        return None

    rows: list[tuple[str, str]] = []
    for raw_line in live_web_context.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("- "):
            line = line[2:]
        parts = [part.strip() for part in line.split("|")]
        title = parts[0] if parts else ""
        snippet = parts[1] if len(parts) > 1 else ""
        if title or snippet:
            rows.append((title, snippet))

    if not rows:
        return None

    first_title, first_snippet = rows[0]
    first_line = re.sub(r"\s+", " ", (first_snippet or first_title)).strip(" .")
    if not first_line:
        return None

    reply = f"From what I found online, sir, {first_line}."
    if len(rows) > 1:
        second_title, second_snippet = rows[1]
        second_line = re.sub(r"\s+", " ", (second_snippet or second_title)).strip(" .")
        if second_line and second_line.lower() != first_line.lower():
            reply += f" Another source adds that {second_line}."
    return reply


def _offline_brain_reply(user_text: str, runtime_context: str, live_web_context: Optional[str] = None) -> str:
    """Generate a local emergency reply when no LLM provider is available."""
    lower = user_text.lower().strip()
    web_reply = _web_context_reply(live_web_context)
    if re.fullmatch(r"(?:hello|hi|hey)(?:\s+jarvis)?[.!? ]*", lower):
        return "Good to hear from you, sir. Local systems are online and listening."
    if "how are you" in lower:
        return "All systems stable and operating locally, sir."
    if "open" in lower and "close" in lower and "app" in lower:
        return "Yes sir. I can open and close applications. Say open Chrome or close Discord and I will handle it."
    if any(token in lower for token in ["what can you do", "capabilities", "help"]):
        return (
            "In local mode I can still run your PC commands, check time and date, perform web lookups, and manage app open and close tasks."
        )
    if "what year" in lower or "what date" in lower or "what time" in lower:
        return f"Local runtime context reads: {runtime_context}."
    if "who are you" in lower:
        return "I am Jarvis, operating in local mode on your machine."
    if web_reply:
        return web_reply
    if any(
        phrase in lower
        for phrase in [
            "why are you offline",
            "why are you in local mode",
            "why are you saying",
            "why aren't you answering",
            "why are you not answering",
            "local recovery",
            "model backend",
            "language model",
            "language core",
            "cloud credits",
        ]
    ):
        return (
            "I'm running in local mode right now, sir. "
            "Direct commands are active, and broader conversation improves once the language model is available."
        )
    if lower in {"what", "why", "how", "who", "when", "where"} or (len(lower.split()) <= 3 and _looks_like_question(lower)):
        return "That question is still a little too vague for me to answer properly, sir. Give me the subject and I will handle it."
    if _looks_like_question(lower):
        return (
            "I could not pull a solid answer for that just now, sir. "
            "Ask me to search it directly and I will look it up, or give me a PC task and I can handle that immediately."
        )
    if lower.startswith(("open ", "search ", "find ", "look up ")):
        return "I heard the intent, sir, but I need the target more clearly. For example, say open YouTube, search Google for the weather, or search YouTube for lofi music."
    return (
        "I'm with you, sir, but I need a little more detail to do something useful with that."
    )


def think(
    user_text: str,
    memory,
    anthropic_client,
    runtime_context: str,
    live_web_context: Optional[str] = None,
) -> Generator[str, None, None]:
    """Stream Jarvis response sentences from cloud and/or local providers."""
    fallback = "My apologies sir, I seem to be having a technical difficulty. Please try again."
    history = memory.get_history()
    if not history or history[-1].get("role") != "user" or history[-1].get("content") != user_text:
        history = [*history, {"role": "user", "content": user_text}]

    system_prompt = _build_system_prompt(runtime_context, live_web_context)
    last_cloud_error = ""
    tried_cloud = False
    last_local_error = ""

    if LOCAL_ONLY_MODE:
        if LOCAL_LLM_FALLBACK:
            try:
                full_response = yield from _yield_sentences_from_chunks(_iter_ollama_chunks(history, system_prompt))
                _finalize_response(memory, full_response, fallback)
                return
            except Exception as exc:
                last_local_error = str(exc)
                print(f"[ERROR] Local Ollama fallback failed: {last_local_error}")

        offline = _offline_brain_reply(user_text, runtime_context, live_web_context=live_web_context)
        _finalize_response(memory, offline, fallback)
        yield offline
        return

    if anthropic_client is not None and PREFER_CLOUD_LLM:
        tried_cloud = True
        try:
            full_response = yield from _yield_sentences_from_chunks(
                _iter_cloud_chunks(anthropic_client, history, system_prompt)
            )
            _finalize_response(memory, full_response, fallback)
            return
        except APIError as exc:
            last_cloud_error = str(exc)
            print(f"[ERROR] Anthropic API error: {last_cloud_error}")
        except Exception as exc:
            last_cloud_error = str(exc)
            print(f"[ERROR] Cloud think() error: {last_cloud_error}")

    if LOCAL_LLM_FALLBACK:
        try:
            if last_cloud_error:
                print("[INFO] Falling back to local Ollama model due to cloud failure.")
            full_response = yield from _yield_sentences_from_chunks(_iter_ollama_chunks(history, system_prompt))
            _finalize_response(memory, full_response, fallback)
            return
        except Exception as exc:
            last_local_error = str(exc)
            print(f"[ERROR] Local Ollama fallback failed: {last_local_error}")

    if anthropic_client is not None and not PREFER_CLOUD_LLM and not tried_cloud:
        try:
            full_response = yield from _yield_sentences_from_chunks(
                _iter_cloud_chunks(anthropic_client, history, system_prompt)
            )
            _finalize_response(memory, full_response, fallback)
            return
        except APIError as exc:
            last_cloud_error = str(exc)
            print(f"[ERROR] Anthropic API error: {last_cloud_error}")
        except Exception as exc:
            last_cloud_error = str(exc)
            print(f"[ERROR] Cloud think() error: {last_cloud_error}")

    if _is_credit_error(last_cloud_error):
        fallback = (
            "My apologies sir, cloud credits appear to be low right now. "
            "I will stay in local mode for you."
        )
    elif not anthropic_client and not LOCAL_LLM_FALLBACK:
        fallback = "I do not have an active language model configured yet, sir."
    elif not anthropic_client and LOCAL_LLM_FALLBACK:
        fallback = _offline_brain_reply(user_text, runtime_context, live_web_context=live_web_context)
    elif last_local_error and not last_cloud_error:
        fallback = _offline_brain_reply(user_text, runtime_context, live_web_context=live_web_context)

    _finalize_response(memory, fallback, fallback)
    yield fallback
