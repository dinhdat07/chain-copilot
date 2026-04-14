from __future__ import annotations

import json
import socket
from urllib import error, request

from llm.config import LLMSettings


class VertexClientError(RuntimeError):
    pass


class VertexGeminiClient:
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
            raise VertexClientError("missing Vertex AI API key")
        if not self.settings.vertex_project_id:
            raise VertexClientError("missing Vertex AI project id")

        endpoint = (
            "https://aiplatform.googleapis.com/v1/projects/"
            f"{self.settings.vertex_project_id}/locations/{self.settings.vertex_region}"
            f"/publishers/google/models/{self.settings.model}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
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
            if exc.code in {401, 403}:
                raise VertexClientError(f"vertex auth error {exc.code}: {detail}") from exc
            if exc.code == 429:
                raise VertexClientError(f"vertex quota error 429: {detail}") from exc
            raise VertexClientError(f"vertex http error {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise VertexClientError(f"vertex connection error: {exc.reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise VertexClientError("vertex request timed out") from exc
        except OSError as exc:
            raise VertexClientError(f"vertex transport error: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise VertexClientError("vertex returned invalid json") from exc

        candidates = raw.get("candidates", [])
        if not candidates:
            raise VertexClientError("vertex returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise VertexClientError("vertex returned empty content")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise VertexClientError("vertex content was not valid json") from exc
