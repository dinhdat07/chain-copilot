from __future__ import annotations

import json
import logging
import requests

from llm.config import LLMSettings
logger = logging.getLogger(__name__)

class FPTClientError(RuntimeError):
    pass

class FPTClient:
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
            raise FPTClientError("missing FPT API key")

        url = "https://mkp-api.fptcloud.com/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.api_key}",
        }

        payload = {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": temperature,
            "max_tokens": 1024,
        }

        try:
            res = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.settings.timeout_s,
            )
            res.raise_for_status()
            raw = res.json()
            logger.debug(f"FPT API response: {raw}")

        except requests.exceptions.HTTPError as exc:
            logger.error(f"FPT HTTP error: {exc}")
            raise FPTClientError(f"fpt http error: {exc}") from exc
        except requests.exceptions.ConnectionError as exc:
            logger.error(f"FPT connection error: {exc}")
            raise FPTClientError(f"fpt connection error: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            logger.error("FPT request timed out")
            raise FPTClientError("fpt request timed out") from exc
        except requests.exceptions.RequestException as exc:
            logger.error(f"FPT transport error: {exc}")
            raise FPTClientError(f"fpt transport error: {exc}") from exc
        except json.JSONDecodeError as exc:
            logger.error(f"FPT returned invalid JSON: {res.text}")
            raise FPTClientError("fpt returned invalid json") from exc

        try:
            # Handle both response formats: with and without 'data' wrapper
            if "data" in raw:
                content = raw["data"]["choices"][0]["message"]["content"]
            else:
                content = raw["choices"][0]["message"]["content"]
            logger.debug(f"Extracted content from FPT response: {content[:100]}...")
        except (KeyError, IndexError) as exc:
            logger.error(f"FPT returned invalid structure: {raw}")
            raise FPTClientError("fpt returned invalid structure") from exc

        try:
            # Remove markdown code blocks if present (e.g., ```json ... ```)
            cleaned_content = content.strip()
            if cleaned_content.startswith("```"):
                # Remove opening ```json or ``` marker
                cleaned_content = cleaned_content.split("```", 2)[1]
                if cleaned_content.startswith("json"):
                    cleaned_content = cleaned_content[4:].lstrip()
                # Remove closing ``` marker
                if cleaned_content.endswith("```"):
                    cleaned_content = cleaned_content.rsplit("```", 1)[0]
                cleaned_content = cleaned_content.strip()
            
            logger.debug(f"Cleaned JSON content: {cleaned_content[:100]}...")
            return json.loads(cleaned_content)
        except json.JSONDecodeError as exc:
            logger.error(f"FPT content was not valid JSON: {content}")
            raise FPTClientError("fpt content was not valid json") from exc
