"""Provider HTTP backends for DirectAIClient (google/openai/anthropic/ollama)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import requests


class ClientBackendsMixin:
    """HTTP backend implementations mixed into DirectAIClient."""

    provider: str
    model: str
    base_url: str
    temperature: float
    max_tokens: int
    system_prompt: str
    history: list[dict[str, str]]

    def get_api_key(self) -> str | None: ...
    def _record_history(self, user_msg: str, ai_msg: str) -> None: ...

    def _call_google(
        self,
        prompt: str,
        stream: bool,
        callback: Callable[[str], None] | None,
    ) -> str:
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY / GOOGLE_API_KEY tidak ditemukan. "
                "Set environment variable, simpan di Web Dashboard, atau jalankan '/menu' -> 'Kelola API Keys'."
            )

        # Try google.genai first if available
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            config = types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            )

            # Build conversation history
            contents: list[Any] = []
            for h in self.history[-10:]:
                role = "user" if h["role"] == "user" else "model"
                contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=h["content"])],
                    )
                )
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)],
                )
            )

            if stream and callback:
                full_text = ""
                for chunk in client.models.generate_content_stream(
                    model=self.model, contents=contents, config=config
                ):
                    if chunk.text:
                        callback(chunk.text)
                        full_text += chunk.text
                self._record_history(prompt, full_text)
                return full_text
            else:
                response = client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                text = response.text or ""
                self._record_history(prompt, text)
                return text
        except Exception:
            # REST Fallback via HTTP
            url = f"{self.base_url}/models/{self.model}:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            payload: dict[str, Any] = {
                "system_instruction": {"parts": [{"text": self.system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": self.temperature,
                    "maxOutputTokens": self.max_tokens,
                },
            }
            res = requests.post(url, headers=headers, json=payload, timeout=120)
            if res.status_code != 200:
                raise RuntimeError(
                    f"Google API Error ({res.status_code}): {res.text}"
                ) from None
            data = res.json()
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                if callback:
                    callback(text)
                self._record_history(prompt, text)
                return text
            return ""

    def _call_openai_compatible(
        self,
        prompt: str,
        stream: bool,
        callback: Callable[[str], None] | None,
    ) -> str:
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError(
                f"API Key untuk provider '{self.provider}' tidak ditemukan.\n"
                f"Masukkan API Key di Web Dashboard atau jalankan '/menu' -> 'Kelola API Keys'."
            )

        messages: list[Any] = [{"role": "system", "content": self.system_prompt}]
        for h in self.history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})

        extra_headers = {}
        if self.provider == "openrouter":
            extra_headers["HTTP-Referer"] = "https://alfa-agent.local"
            extra_headers["X-Title"] = "ALFA Sovereign CLI"

        # Try using openai client if installed
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url=self.base_url,
                default_headers=extra_headers or None,
            )
            if stream and callback:
                response: Any = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    stream=True,
                )
                full_text = ""
                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta:
                        delta = chunk.choices[0].delta.content or ""
                        if delta:
                            callback(delta)
                            full_text += delta
                self._record_history(prompt, full_text)
                return full_text
            else:
                resp: Any = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    stream=False,
                )
                text: str = resp.choices[0].message.content or ""
                self._record_history(prompt, text)
                return text
        except Exception:
            # REST Fallback
            url = f"{str(self.base_url).rstrip('/')}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                **extra_headers,
            }
            body: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": stream and callback is not None,
            }

            if stream and callback:
                res = requests.post(
                    url, headers=headers, json=body, stream=True, timeout=120
                )
                if res.status_code != 200:
                    raise RuntimeError(
                        f"{self.provider.upper()} API Error ({res.status_code}): {res.text}"
                    ) from None
                full_text = ""
                for line in res.iter_lines():
                    if line:
                        line_str = line.decode("utf-8")
                        if line_str.startswith("data: "):
                            raw_chunk = line_str[6:].strip()
                            if raw_chunk == "[DONE]":
                                break
                            try:
                                chunk_json = json.loads(raw_chunk)
                                delta = (
                                    chunk_json.get("choices", [{}])[0]
                                    .get("delta", {})
                                    .get("content", "")
                                )
                                if delta:
                                    callback(delta)
                                    full_text += delta
                            except Exception:
                                pass
                self._record_history(prompt, full_text)
                return full_text
            else:
                body["stream"] = False
                res = requests.post(url, headers=headers, json=body, timeout=120)
                if res.status_code != 200:
                    raise RuntimeError(
                        f"{self.provider.upper()} API Error ({res.status_code}): {res.text}"
                    ) from None
                data = res.json()
                text = data["choices"][0]["message"]["content"]
                if callback:
                    callback(text)
                self._record_history(prompt, text)
                return text

    def _call_anthropic(
        self,
        prompt: str,
        stream: bool,
        callback: Callable[[str], None] | None,
    ) -> str:
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY tidak ditemukan.")

        chat_messages: list[Any] = []
        for h in self.history[-10:]:
            chat_messages.append({"role": h["role"], "content": h["content"]})
        chat_messages.append({"role": "user", "content": prompt})

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            if stream and callback:
                with client.messages.stream(
                    max_tokens=self.max_tokens,
                    system=self.system_prompt,
                    messages=chat_messages,
                    model=self.model,
                    temperature=self.temperature,
                ) as stream_resp:
                    full_text = ""
                    for delta in stream_resp.text_stream:
                        callback(delta)
                        full_text += delta
                self._record_history(prompt, full_text)
                return full_text
            else:
                resp = client.messages.create(
                    max_tokens=self.max_tokens,
                    system=self.system_prompt,
                    messages=chat_messages,
                    model=self.model,
                    temperature=self.temperature,
                )
                text: str = str(getattr(resp.content[0], "text", ""))
                self._record_history(prompt, text)
                return text
        except Exception:
            # REST Fallback
            url = f"{str(self.base_url).rstrip('/')}/v1/messages"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
            body: dict[str, Any] = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": self.system_prompt,
                "messages": chat_messages,
                "temperature": self.temperature,
            }
            res = requests.post(url, headers=headers, json=body, timeout=120)
            if res.status_code != 200:
                raise RuntimeError(
                    f"Anthropic API Error ({res.status_code}): {res.text}"
                ) from None
            data = res.json()
            text = data["content"][0]["text"]
            if callback:
                callback(text)
            self._record_history(prompt, text)
            return text

    def _call_ollama(
        self,
        prompt: str,
        stream: bool,
        callback: Callable[[str], None] | None,
    ) -> str:
        messages = [{"role": "system", "content": self.system_prompt}]
        for h in self.history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})

        url = f"{self.base_url.rstrip('/')}/api/chat"
        headers = {"Content-Type": "application/json"}
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream and callback is not None,
            "options": {"temperature": self.temperature},
        }

        try:
            if stream and callback:
                res = requests.post(
                    url, headers=headers, json=body, stream=True, timeout=120
                )
                if res.status_code != 200:
                    raise RuntimeError(f"Ollama Error ({res.status_code}): {res.text}")
                full_text = ""
                for line in res.iter_lines():
                    if line:
                        chunk = json.loads(line.decode("utf-8"))
                        piece = chunk.get("message", {}).get("content", "")
                        callback(piece)
                        full_text += piece
                self._record_history(prompt, full_text)
                return full_text
            else:
                res = requests.post(url, headers=headers, json=body, timeout=120)
                if res.status_code != 200:
                    raise RuntimeError(f"Ollama Error ({res.status_code}): {res.text}")
                data = res.json()
                text: str = data.get("message", {}).get("content", "")
                self._record_history(prompt, text)
                return text
        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                f"Tidak dapat terhubung ke Ollama di {self.base_url}. "
                "Pastikan service Ollama aktif ('ollama serve')."
            ) from None
