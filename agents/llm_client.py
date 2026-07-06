from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any


class OpenAILowCostClient:
    """Small wrapper around the OpenAI Responses API.

    The architecture uses lower-cost GPT models for routine checks and a
    stronger model only for escalations. Model names are environment-driven so
    they can be changed without code edits.
    """

    def __init__(
        self,
        api_key: str | None = None,
        low_model: str | None = None,
        escalate_model: str | None = None,
        role_models: dict[str, str] | None = None,
        timeout_seconds: int = 120,
        max_retries: int | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.low_model = low_model or os.getenv("OPENAI_LOW_MODEL", "gpt-4.1-mini")
        self.escalate_model = escalate_model or os.getenv("OPENAI_ESCALATE_MODEL", "gpt-4.1")
        self.role_models = role_models or {
            "rule": os.getenv("OPENAI_RULE_MODEL", self.low_model),
            "table": os.getenv("OPENAI_TABLE_MODEL", os.getenv("OPENAI_STRONG_MODEL", self.escalate_model)),
            "attachment": os.getenv("OPENAI_ATTACHMENT_MODEL", self.low_model),
            "general": os.getenv("OPENAI_GENERAL_MODEL", self.low_model),
            "parse_audit": os.getenv("OPENAI_PARSE_AUDIT_MODEL", self.low_model),
        }
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries if max_retries is not None else int(os.getenv("OPENAI_MAX_RETRIES", "4"))

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def model_for(self, model_role: str | None = None, *, escalation: bool = False) -> str:
        if escalation:
            return self.escalate_model
        if model_role and model_role in self.role_models:
            return self.role_models[model_role]
        return self.low_model

    def json_response(
        self,
        system: str,
        user: str,
        *,
        escalation: bool = False,
        model_role: str | None = None,
        temperature: float = 0,
    ) -> dict[str, Any]:
        text = self.text_response(system, user, escalation=escalation, model_role=model_role, temperature=temperature)
        try:
            return parse_json_object(text)
        except json.JSONDecodeError as exc:
            repaired = self.repair_json_response(
                text,
                error=str(exc),
                escalation=escalation,
                model_role=model_role,
            )
            try:
                return parse_json_object(repaired)
            except json.JSONDecodeError as repair_exc:
                excerpt = text.strip().replace("\n", " ")[:500]
                raise RuntimeError(
                    f"LLM JSON parse failed after repair attempt: {repair_exc}. Original response excerpt: {excerpt}"
                ) from repair_exc

    def repair_json_response(
        self,
        broken_text: str,
        *,
        error: str,
        escalation: bool = False,
        model_role: str | None = None,
    ) -> str:
        system = "깨진 JSON을 유효한 JSON 객체 하나로만 복구하는 도구입니다. 설명 없이 JSON만 반환하세요."
        user = json.dumps(
            {
                "instruction": "원문 의미와 필드명을 유지하고 문법 오류만 수정하세요. JSON 객체 하나만 반환하세요.",
                "parse_error": error,
                "broken_json_text": broken_text,
            },
            ensure_ascii=False,
        )
        return self.text_response(system, user, escalation=escalation, model_role=model_role, temperature=0)

    def text_response(
        self,
        system: str,
        user: str,
        *,
        escalation: bool = False,
        model_role: str | None = None,
        temperature: float = 0,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        payload = {
            "model": self.model_for(model_role, escalation=escalation),
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        response = self._post_json("https://api.openai.com/v1/responses", payload)
        return extract_response_text(response)

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                if is_retryable_http_error(exc.code) and attempt < self.max_retries:
                    time.sleep(api_retry_wait_seconds(exc, error_body, attempt))
                    continue
                raise RuntimeError(f"OpenAI API call failed: HTTP {exc.code} {error_body}") from exc
            except urllib.error.URLError as exc:
                if attempt < self.max_retries:
                    time.sleep(transient_wait_seconds(attempt))
                    continue
                raise RuntimeError(f"OpenAI API call failed: {exc.reason}") from exc
            except (TimeoutError, socket.timeout) as exc:
                if attempt < self.max_retries:
                    time.sleep(transient_wait_seconds(attempt))
                    continue
                raise RuntimeError(f"OpenAI API call timed out after retry attempts: {exc}") from exc
        raise RuntimeError("OpenAI API call failed after retry attempts.")


class DisabledLlmClient:
    def is_configured(self) -> bool:
        return False

    def json_response(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("LLM client is disabled.")

    def text_response(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("LLM client is disabled.")


def extract_response_text(response_json: dict[str, Any]) -> str:
    if response_json.get("output_text"):
        return str(response_json["output_text"])
    chunks: list[str] = []
    for item in response_json.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                chunks.append(str(content.get("text", "")))
    return "\n".join(chunks)


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json\n", "", 1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end >= start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def rate_limit_wait_seconds(exc: urllib.error.HTTPError, body: str, attempt: int) -> float:
    retry_after = exc.headers.get("retry-after") if exc.headers else None
    if retry_after:
        try:
            return min(120.0, max(1.0, float(retry_after)))
        except ValueError:
            pass
    match = re.search(r"try again in ([0-9]+(?:\.[0-9]+)?)s", body, re.IGNORECASE)
    if match:
        return min(120.0, max(1.0, float(match.group(1)) + 1.0))
    return min(60.0, 2.0 * (attempt + 1))


def api_retry_wait_seconds(exc: urllib.error.HTTPError, body: str, attempt: int) -> float:
    if exc.code == 429:
        return rate_limit_wait_seconds(exc, body, attempt)
    return transient_wait_seconds(attempt)


def transient_wait_seconds(attempt: int) -> float:
    return min(30.0, 2.0 * (attempt + 1))


def is_retryable_http_error(status_code: int) -> bool:
    return status_code == 429 or status_code in {500, 502, 503, 504}
