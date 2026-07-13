"""دستیار هوش مصنوعی چندارائه‌دهنده‌ای برای SoroPy WebSocket.

Providerهای پشتیبانی‌شده: OpenAI، OpenAI-compatible، Gemini، Claude و Ollama.
وابستگی‌های AI فقط داخل adapterها import می‌شوند و dependency اصلی SoroPy نیستند.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

PHONE = os.getenv("SOROPY_PHONE", "09123456789")
PROVIDER = os.getenv(
    "AI_PROVIDER",
    "ollama",
).strip().casefold()
MODEL = os.getenv("AI_MODEL", "llama3.2")
SYSTEM_PROMPT = os.getenv(
    "AI_SYSTEM_PROMPT",
    "تو یک دستیار فارسی دقیق، مؤدب و مختصر هستی.",
)

AI_PRIVATE_ONLY = os.getenv("AI_PRIVATE_ONLY", "true").strip().casefold() != "false"
SOROPY_AI_GROUP = os.getenv("SOROPY_AI_GROUP", "")
AI_MAX_WORKERS = int(os.getenv("AI_MAX_WORKERS", "3"))
AI_RATE_LIMIT = int(os.getenv("AI_RATE_LIMIT", "3"))
AI_HISTORY_MESSAGES = int(os.getenv("AI_HISTORY_MESSAGES", "6"))
AI_MAX_REPLY_CHARS = int(os.getenv("AI_MAX_REPLY_CHARS", "3500"))


def _now() -> float:
    return time.time()


def _env_required(name: str, install_hint: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"متغیر {name} تنظیم نشده است. {install_hint}")
    return value


def split_text(text: str, max_chars: int = AI_MAX_REPLY_CHARS) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: List[str] = []
    remaining = text
    while remaining:
        part = remaining[:max_chars]
        cut = max(part.rfind("\n"), part.rfind(". "), part.rfind("؟ "))
        if cut > max_chars // 2:
            part = remaining[: cut + 1]
        chunks.append(part.strip())
        remaining = remaining[len(part):].strip()
    return [chunk for chunk in chunks if chunk]


class AIProvider:
    def __init__(self, provider: str = PROVIDER, model: str = MODEL):
        self.provider = provider.strip().casefold()
        self.model = model

    def _prompt(self, history: Sequence[Dict[str, str]], user_text: str) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(
            {"role": item["role"], "content": item["content"]}
            for item in history
            if item.get("role") in {"user", "assistant"} and item.get("content")
        )
        messages.append({"role": "user", "content": user_text})
        return messages

    def complete(self, history: Sequence[Dict[str, str]], user_text: str) -> str:
        messages = self._prompt(history, user_text)
        if self.provider in {"openai", "openai-compatible", "compatible"}:
            return self._openai(messages)
        if self.provider in {"gemini", "google"}:
            return self._gemini(messages)
        if self.provider in {"anthropic", "claude"}:
            return self._claude(messages)
        if self.provider == "ollama":
            return self._ollama(messages)
        raise RuntimeError(f"ارائه‌دهنده AI ناشناخته است: {self.provider}")

    def _openai(self, messages: Sequence[Dict[str, str]]) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("برای OpenAI نصب کنید: pip install openai") from exc
        api_key = _env_required("OPENAI_API_KEY", "برای OpenAI کلید لازم است.")
        base_url = os.getenv("OPENAI_BASE_URL", "").strip()
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)
        result = client.chat.completions.create(model=self.model, messages=list(messages))
        return result.choices[0].message.content or ""

    def _gemini(self, messages: Sequence[Dict[str, str]]) -> str:
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError("برای Gemini نصب کنید: pip install google-genai") from exc
        api_key = _env_required("GEMINI_API_KEY", "برای Gemini کلید لازم است.")
        client = genai.Client(api_key=api_key)
        text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        result = client.models.generate_content(model=self.model, contents=text)
        return getattr(result, "text", "") or ""

    def _claude(self, messages: Sequence[Dict[str, str]]) -> str:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("برای Claude نصب کنید: pip install anthropic") from exc
        api_key = _env_required("ANTHROPIC_API_KEY", "برای Claude کلید لازم است.")
        client = anthropic.Anthropic(api_key=api_key)
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else SYSTEM_PROMPT
        chat_messages = [m for m in messages if m["role"] in {"user", "assistant"}]
        result = client.messages.create(
            model=self.model,
            max_tokens=1200,
            system=system,
            messages=chat_messages,
        )
        return "".join(getattr(block, "text", "") for block in result.content)

    def _ollama(self, messages: Sequence[Dict[str, str]]) -> str:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        url = base_url + "/api/chat"
        payload = json.dumps(
            {"model": self.model, "messages": list(messages), "stream": False},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("اتصال به Ollama ناموفق بود؛ ابتدا `ollama serve` را اجرا کنید.") from exc
        return str((data.get("message") or {}).get("content") or "")


@dataclass(frozen=True)
class IncomingAIMessage:
    message_id: str
    chat_id: str
    chat_name: str
    sender_id: str
    text: str
    is_private: bool
    is_group: bool
    is_outgoing: bool

    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> "IncomingAIMessage":
        return cls(
            message_id=str(data.get("message_id") or ""),
            chat_id=str(data.get("chat_id") or data.get("chat_name") or ""),
            chat_name=str(data.get("chat_name") or ""),
            sender_id=str(data.get("sender_id") or data.get("chat_id") or ""),
            text=str(data.get("text") or ""),
            is_private=bool(data.get("is_private")),
            is_group=bool(data.get("is_group")),
            is_outgoing=bool(data.get("is_outgoing")),
        )


def group_trigger_text(text: str) -> Optional[str]:
    stripped = str(text or "").strip()
    if stripped.startswith("/ai"):
        return stripped[3:].strip()
    if stripped.startswith("هوش:"):
        return stripped.split(":", 1)[1].strip()
    return None


def should_answer(item: IncomingAIMessage) -> Tuple[bool, str]:
    if item.is_outgoing or not item.text.strip():
        return False, ""
    if item.is_private:
        return True, item.text.strip()
    if AI_PRIVATE_ONLY or not item.is_group or item.chat_name != SOROPY_AI_GROUP:
        return False, ""
    triggered = group_trigger_text(item.text)
    return (bool(triggered), triggered or "")


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    def allow(self, sender_id: str) -> bool:
        now = _now()
        with self._lock:
            events = self._events[sender_id]
            while events and now - events[0] > self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


class AIAssistantBot:
    def __init__(self, client: Any, provider: Optional[AIProvider] = None):
        self.client = client
        self.provider = provider or AIProvider()
        self.pool = ThreadPoolExecutor(max_workers=AI_MAX_WORKERS)
        self.rate_limiter = RateLimiter(AI_RATE_LIMIT)
        self.histories: Dict[str, Deque[Dict[str, str]]] = defaultdict(
            lambda: deque(maxlen=max(2, AI_HISTORY_MESSAGES * 2))
        )
        self.seen: Deque[str] = deque(maxlen=2000)
        self.seen_set = set()
        self.lock = threading.RLock()

    def close(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=True)

    def on_event(self, event: Any) -> None:
        item = IncomingAIMessage.from_payload(getattr(event, "data", None) or {})
        ok, prompt = should_answer(item)
        if not ok:
            return
        if not self._mark_seen(item.message_id or f"{item.chat_id}:{item.text}"):
            return
        if not self.rate_limiter.allow(item.sender_id or item.chat_id):
            self._send(item, "لطفاً کمی آهسته‌تر پیام بدهید.")
            return
        self.pool.submit(self._answer, item, prompt)

    def _mark_seen(self, message_id: str) -> bool:
        with self.lock:
            if message_id in self.seen_set:
                return False
            self.seen.append(message_id)
            self.seen_set.add(message_id)
            while len(self.seen_set) > self.seen.maxlen:
                old = self.seen.popleft()
                self.seen_set.discard(old)
            return True

    def _answer(self, item: IncomingAIMessage, prompt: str) -> None:
        try:
            with self.lock:
                history = list(self.histories[item.chat_id])
            reply = self.provider.complete(history, prompt).strip()
            if not reply:
                reply = "پاسخی دریافت نشد."
            with self.lock:
                self.histories[item.chat_id].append({"role": "user", "content": prompt})
                self.histories[item.chat_id].append({"role": "assistant", "content": reply})
            self._send(item, reply)
        except Exception as exc:
            print(f"AI provider error: {type(exc).__name__}: {exc}")
            self._send(item, "فعلاً امکان پاسخ‌گویی هوش مصنوعی وجود ندارد.")

    def _send(self, item: IncomingAIMessage, text: str) -> None:
        target = item.chat_name or item.chat_id
        chunks = split_text(text, AI_MAX_REPLY_CHARS)
        for index, chunk in enumerate(chunks):
            if index == 0 and item.message_id:
                self.client.reply(target, item.message_id, chunk)
            else:
                self.client.send_message(target, chunk)


def main() -> None:
    from soropy import SoroushClient

    client = SoroushClient(PHONE, backend="websocket", auto_reply_private_only=True)
    bot = AIAssistantBot(client)
    try:
        client.on("new_message", bot.on_event)
        client.login(code_callback=lambda: input("کد پیامک‌شده: ").strip())
        print("دستیار AI فعال شد. برای خروج Ctrl+C بزنید.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("در حال خروج...")
    finally:
        bot.close()
        client.close()


if __name__ == "__main__":
    main()
