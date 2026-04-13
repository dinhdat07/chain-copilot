from __future__ import annotations

import json
import socket
from urllib import error, request

from llm.config import LLMSettings


class GeminiClientError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    def generate_json(
        self,
        *,
        prompt: str,
        schema: dict,
        temperature: float = 0.2,
    ) -> dict:
        if not self.settings.api_key:
            raise GeminiClientError("missing Gemini API key")

        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.model}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt,
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.settings.api_key,
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.settings.timeout_s) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise GeminiClientError(f"gemini http error {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise GeminiClientError(f"gemini connection error: {exc.reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise GeminiClientError("gemini request timed out") from exc
        except OSError as exc:
            raise GeminiClientError(f"gemini transport error: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise GeminiClientError("gemini returned invalid json") from exc

        candidates = raw.get("candidates", [])
        if not candidates:
            raise GeminiClientError("gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise GeminiClientError("gemini returned empty content")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiClientError("gemini content was not valid json") from exc
