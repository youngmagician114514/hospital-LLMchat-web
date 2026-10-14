from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Literal, Protocol

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("hospital-chat")


OUTPUT_LABELS = ("西医诊断", "主证", "兼证", "方药", "理由")
OUTPUT_TEMPLATE = "西医诊断：\n主证：\n兼证：\n方药：\n理由："
ThinkingLevel = Literal["off", "low", "high", "max"]


def _load_dotenv_if_exists() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv_if_exists()


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid int env %s=%r, fallback to %s", name, value, default)
        return default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid float env %s=%r, fallback to %s", name, value, default)
        return default


@dataclass(frozen=True)
class Settings:
    model_provider: str = os.getenv("MODEL_PROVIDER", "stub").strip()

    # Generic OpenAI-compatible provider config
    openai_api_base: str = os.getenv("OPENAI_API_BASE", "").strip()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

    # vLLM decoupled config
    vllm_api_base: str = os.getenv("VLLM_API_BASE", "http://127.0.0.1:8001/v1").strip()
    vllm_api_key: str = os.getenv("VLLM_API_KEY", "").strip()
    vllm_model: str = os.getenv("VLLM_MODEL", "qwen2.5-7b-instruct").strip()

    # Shared inference params for OpenAI-compatible backends
    generation_temperature: float = _float_env("GENERATION_TEMPERATURE", 0.2)
    generation_top_p: float = _float_env("GENERATION_TOP_P", 0.9)
    generation_max_tokens: int = _int_env("GENERATION_MAX_TOKENS", 512)
    thinking_max_tokens: int = _int_env("THINKING_MAX_TOKENS", 8192)

    # Runtime
    request_timeout_seconds: int = _int_env("REQUEST_TIMEOUT_SECONDS", 120)
    max_concurrent_model_calls: int = _int_env("MAX_CONCURRENT_MODEL_CALLS", 200)
    max_history_messages: int = _int_env("MAX_HISTORY_MESSAGES", 20)
    session_ttl_seconds: int = _int_env("SESSION_TTL_SECONDS", 3600)
    session_cleanup_interval_seconds: int = _int_env("SESSION_CLEANUP_INTERVAL_SECONDS", 300)


settings = Settings()


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    session_id: str | None = Field(default=None, max_length=128)
    history: list[ChatMessage] = Field(default_factory=list)
    use_server_history: bool = True
    thinking_level: ThinkingLevel = "low"


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    model: str
    latency_ms: int
    history: list[ChatMessage]
    thinking_level: ThinkingLevel


class ResetSessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)


class HealthResponse(BaseModel):
    status: str
    provider: str
    active_sessions: int
    max_concurrent_model_calls: int


class PromptResponse(BaseModel):
    system_prompt: str
    required_output_format: str


class FormAutofillData(BaseModel):
    visitType: str = ""
    patientGender: str = ""
    patientAge: str = ""
    chiefComplaint: str = ""
    presentIllness: str = ""
    physicalExam: str = ""
    imagingFindings: str = ""
    tonguePulse: str = ""
    historyAllergy: str = ""
    firstVisitDate: str = ""
    firstVisitDiagnosis: str = ""
    firstVisitPrescription: str = ""
    afterChange: str = ""


class FormAutofillRequest(BaseModel):
    source_text: str = Field(min_length=10, max_length=12000)
    thinking_level: ThinkingLevel = "low"


class FormAutofillResponse(BaseModel):
    data: FormAutofillData
    model: str
    latency_ms: int
    raw_reply: str
    thinking_level: ThinkingLevel


if hasattr(FormAutofillData, "model_fields"):
    FORM_AUTOFILL_FIELDS = tuple(FormAutofillData.model_fields.keys())
else:
    FORM_AUTOFILL_FIELDS = tuple(FormAutofillData.__fields__.keys())


def _model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _extract_field(raw: str, label: str, next_label: str | None) -> str:
    if next_label is None:
        pattern = rf"{re.escape(label)}[：:]\s*(.*)\s*$"
    else:
        pattern = rf"{re.escape(label)}[：:]\s*(.*?)\s*(?={re.escape(next_label)}[：:])"
    match = re.search(pattern, raw, flags=re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def _normalize_output_format(raw_text: str) -> str:
    raw = (raw_text or "").strip()
    extracted: dict[str, str] = {}
    for idx, label in enumerate(OUTPUT_LABELS):
        next_label = OUTPUT_LABELS[idx + 1] if idx + 1 < len(OUTPUT_LABELS) else None
        extracted[label] = _extract_field(raw, label, next_label)

    has_structured = any(extracted.values())
    if not has_structured:
        extracted = {
            "西医诊断": "未明确",
            "主证": "未明确",
            "兼证": "未明确",
            "方药": "未明确",
            "理由": raw or "未明确",
        }
    else:
        for label in OUTPUT_LABELS:
            if not extracted[label]:
                extracted[label] = "未明确"

    return (
        f"西医诊断：{extracted['西医诊断']}\n"
        f"主证：{extracted['主证']}\n"
        f"兼证：{extracted['兼证']}\n"
        f"方药：{extracted['方药']}\n"
        f"理由：{extracted['理由']}"
    )


FORM_SOURCE_LABELS = (
    "就诊类型",
    "初诊时间",
    "初诊诊断",
    "初诊方药与剂量",
    "初诊方药",
    "服药后变化",
    "主诉",
    "现病史",
    "查体",
    "体格检查",
    "专科检查",
    "辅助检查",
    "影像学/检验",
    "影像学检查",
    "中医四诊分析",
    "舌脉",
    "舌象脉象",
    "既往史",
    "家族史",
    "过敏史",
    "流行病学史",
    "性别",
    "年龄",
    "姓名",
)

FORM_EMPTY_VALUES = {
    "",
    "未提及",
    "未提供",
    "未填写",
    "未明确",
    "未知",
    "无",
    "暂无",
    "不详",
    "未见",
    "none",
    "null",
}

FORM_IMPORT_SYSTEM_PROMPT = (
    "你是医院内网病历整理助手。"
    "任务：从一段中文病历原文、门诊记录或语音转写文本中提取表单字段。"
    "每次请求都视为全新对话，禁止引用任何历史上下文。"
    "你只能输出一个 JSON 对象，不要输出 markdown、解释或额外文字。"
    "JSON 必须包含以下全部键："
    '{"visitType":"","patientGender":"","patientAge":"","chiefComplaint":"","presentIllness":"","physicalExam":"","imagingFindings":"","tonguePulse":"","historyAllergy":"","firstVisitDate":"","firstVisitDiagnosis":"","firstVisitPrescription":"","afterChange":""}'
    "字段规则："
    "1) 未提及填空字符串，禁止编造。"
    "2) visitType 只允许“初诊”或“复诊”；若明确写到复诊/随访/复查，或出现初诊信息、服药后变化等复诊线索，则填“复诊”，否则填“初诊”。"
    "3) patientGender 只填“男”或“女”；patientAge 只填数字，不带“岁”。"
    "4) chiefComplaint 提取主诉；presentIllness 提取现病史、病程经过、诱因及加重/缓解因素。"
    "5) physicalExam 提取查体、专科检查和阳性体征。"
    "6) imagingFindings 提取辅助检查、MRI/CT/X线/检验结论。"
    "7) tonguePulse 提取中医四诊、舌象、苔、脉、睡眠、二便等中医补充信息。"
    "8) historyAllergy 提取既往史、家族史、过敏史、流行病学史及其他补充信息。"
    "9) 只有在复诊时，firstVisitDate、firstVisitDiagnosis、firstVisitPrescription、afterChange 才填写；否则保留空字符串。"
    "10) 保留原文关键信息，但删去与字段无关的噪声。"
)


def _default_form_autofill_data() -> dict[str, str]:
    return {field: "" for field in FORM_AUTOFILL_FIELDS}


def _normalize_free_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [_normalize_free_text(item) for item in value]
        return "；".join(part for part in parts if part)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = _normalize_free_text(item)
            if text:
                parts.append(f"{key}：{text}")
        return "；".join(parts)

    text = str(value).strip().replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if text.lower() in FORM_EMPTY_VALUES or text in FORM_EMPTY_VALUES:
        return ""
    return text


def _normalize_visit_type(value: str, source_text: str = "") -> str:
    merged = f"{value} {source_text}"
    if any(token in merged for token in ("复诊", "复查", "随访", "随诊", "二诊", "三诊")):
        return "复诊"
    if any(token in merged for token in ("服药后", "初诊时间", "初诊诊断", "初诊方药", "前次处方")):
        return "复诊"
    return "初诊"


def _normalize_gender(value: str) -> str:
    if "男" in value:
        return "男"
    if "女" in value:
        return "女"
    return ""


def _normalize_age(value: str) -> str:
    match = re.search(r"(\d{1,3})", value)
    return match.group(1) if match else ""


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        return {}

    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text, flags=re.IGNORECASE)
    candidate = fenced.group(1).strip() if fenced else text
    if not fenced:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        candidate = candidate[start : end + 1]

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_form_autofill_data(payload: dict[str, Any], source_text: str) -> dict[str, str]:
    normalized = _default_form_autofill_data()
    for field in FORM_AUTOFILL_FIELDS:
        normalized[field] = _normalize_free_text(payload.get(field, ""))

    normalized["visitType"] = _normalize_visit_type(normalized["visitType"], source_text)
    normalized["patientGender"] = _normalize_gender(normalized["patientGender"])
    normalized["patientAge"] = _normalize_age(normalized["patientAge"])

    has_followup_fields = any(
        normalized[field]
        for field in ("firstVisitDate", "firstVisitDiagnosis", "firstVisitPrescription", "afterChange")
    )
    if has_followup_fields:
        normalized["visitType"] = "复诊"
    elif normalized["visitType"] != "复诊":
        for field in ("firstVisitDate", "firstVisitDiagnosis", "firstVisitPrescription", "afterChange"):
            normalized[field] = ""

    return normalized


def _extract_complete_json_fields(raw_text: str) -> dict[str, Any]:
    """Read only completed top-level values; never guess a truncated string/number."""
    start = raw_text.find("{")
    if start == -1:
        return {}
    decoder = json.JSONDecoder()
    cursor = start + 1
    fields: dict[str, Any] = {}
    while cursor < len(raw_text):
        while cursor < len(raw_text) and raw_text[cursor].isspace():
            cursor += 1
        try:
            key, cursor = decoder.raw_decode(raw_text, cursor)
            if not isinstance(key, str):
                break
            while cursor < len(raw_text) and raw_text[cursor].isspace():
                cursor += 1
            if cursor >= len(raw_text) or raw_text[cursor] != ":":
                break
            cursor += 1
            while cursor < len(raw_text) and raw_text[cursor].isspace():
                cursor += 1
            value, end = decoder.raw_decode(raw_text, cursor)
        except json.JSONDecodeError:
            break
        cursor = end
        while cursor < len(raw_text) and raw_text[cursor].isspace():
            cursor += 1
        if cursor >= len(raw_text) or raw_text[cursor] not in ",}":
            break
        if key in FORM_AUTOFILL_FIELDS:
            fields[key] = value
        if raw_text[cursor] == "}":
            break
        cursor += 1
    return fields


def _extract_labeled_segments(raw_text: str, labels: tuple[str, ...]) -> list[tuple[str, str]]:
    if not raw_text or not labels:
        return []

    label_pattern = "|".join(sorted((re.escape(label) for label in labels), key=len, reverse=True))
    stop_labels = tuple(label for label in FORM_SOURCE_LABELS if label not in labels)
    stop_pattern = "|".join(sorted((re.escape(label) for label in stop_labels), key=len, reverse=True))
    pattern = rf"({label_pattern})[：:]\s*(.*?)(?=(?:{stop_pattern})[：:]|$)"

    segments: list[tuple[str, str]] = []
    for match in re.finditer(pattern, raw_text, flags=re.DOTALL):
        label = match.group(1)
        value = _normalize_free_text(match.group(2))
        if value:
            segments.append((label, value))
    return segments


def _combine_labeled_segments(segments: list[tuple[str, str]], *, always_include_label: bool = False) -> str:
    if not segments:
        return ""
    include_label = always_include_label or len(segments) > 1
    pieces = [
        f"{label}：{value}" if include_label else value
        for label, value in segments
        if value
    ]
    return "\n".join(pieces)


def _extract_first_inline_value(raw_text: str, label: str, pattern: str) -> str:
    match = re.search(rf"{re.escape(label)}[：:]\s*{pattern}", raw_text)
    return match.group(1).strip() if match else ""


def _build_heuristic_form_autofill_data(source_text: str) -> dict[str, str]:
    normalized = source_text.replace("\r\n", "\n").replace("\r", "\n")
    extracted = _default_form_autofill_data()

    extracted["patientGender"] = _normalize_gender(
        _extract_first_inline_value(normalized, "性别", r"(男|女)")
    )
    extracted["patientAge"] = _normalize_age(
        _extract_first_inline_value(normalized, "年龄", r"(\d{1,3}(?:岁)?)")
    )

    extracted["chiefComplaint"] = _combine_labeled_segments(
        _extract_labeled_segments(normalized, ("主诉",))
    )
    extracted["presentIllness"] = _combine_labeled_segments(
        _extract_labeled_segments(normalized, ("现病史",))
    )
    extracted["physicalExam"] = _combine_labeled_segments(
        _extract_labeled_segments(normalized, ("查体", "体格检查", "专科检查")),
        always_include_label=True,
    )
    extracted["imagingFindings"] = _combine_labeled_segments(
        _extract_labeled_segments(normalized, ("辅助检查", "影像学/检验", "影像学检查")),
        always_include_label=True,
    )
    extracted["tonguePulse"] = _combine_labeled_segments(
        _extract_labeled_segments(normalized, ("中医四诊分析", "舌脉", "舌象脉象")),
        always_include_label=True,
    )
    extracted["historyAllergy"] = _combine_labeled_segments(
        _extract_labeled_segments(normalized, ("既往史", "家族史", "过敏史", "流行病学史")),
        always_include_label=True,
    )
    extracted["firstVisitDate"] = _combine_labeled_segments(
        _extract_labeled_segments(normalized, ("初诊时间",))
    )
    extracted["firstVisitDiagnosis"] = _combine_labeled_segments(
        _extract_labeled_segments(normalized, ("初诊诊断",))
    )
    extracted["firstVisitPrescription"] = _combine_labeled_segments(
        _extract_labeled_segments(normalized, ("初诊方药与剂量", "初诊方药")),
        always_include_label=True,
    )
    extracted["afterChange"] = _combine_labeled_segments(
        _extract_labeled_segments(normalized, ("服药后变化",))
    )
    extracted["visitType"] = _normalize_visit_type("", normalized)

    return _normalize_form_autofill_data(extracted, normalized)


def _merge_form_autofill_data(primary: dict[str, str], fallback: dict[str, str], source_text: str) -> dict[str, str]:
    merged = _default_form_autofill_data()
    for field in FORM_AUTOFILL_FIELDS:
        merged[field] = primary.get(field, "") or fallback.get(field, "")
    return _normalize_form_autofill_data(merged, source_text)


@dataclass
class SessionState:
    history: list[ChatMessage] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_access: float = field(default_factory=time.time)


class InMemorySessionStore:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, SessionState] = {}
        self._sessions_lock = asyncio.Lock()

    async def get_or_create(self, session_id: str) -> SessionState:
        now = time.time()
        async with self._sessions_lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = SessionState()
                self._sessions[session_id] = state
            state.last_access = now
            return state

    async def clear(self, session_id: str) -> bool:
        async with self._sessions_lock:
            return self._sessions.pop(session_id, None) is not None

    async def cleanup_expired(self) -> int:
        now = time.time()
        async with self._sessions_lock:
            expired = [
                key
                for key, state in self._sessions.items()
                if now - state.last_access > self._ttl_seconds
            ]
            for key in expired:
                self._sessions.pop(key, None)
            return len(expired)

    async def active_sessions(self) -> int:
        async with self._sessions_lock:
            return len(self._sessions)


class LLMProvider(Protocol):
    model_name: str

    async def generate(self, messages: list[ChatMessage], *, thinking_level: ThinkingLevel = "off") -> str:
        pass

    async def generate_stream(self, messages: list[ChatMessage], *, thinking_level: ThinkingLevel = "off") -> AsyncIterator[str]:
        pass


class StubLLMProvider:
    model_name = "stub-test"

    async def generate(self, messages: list[ChatMessage], *, thinking_level: ThinkingLevel = "off") -> str:
        await asyncio.sleep(0.02)
        return "西医诊断：test\n主证：test\n兼证：test\n方药：test\n理由：test"

    async def generate_stream(self, messages: list[ChatMessage], *, thinking_level: ThinkingLevel = "off") -> AsyncIterator[str]:
        text = await self.generate(messages, thinking_level=thinking_level)
        for token in text:
            await asyncio.sleep(0.003)
            yield token


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> None:
        self.model_name = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._temperature = temperature
        self._top_p = top_p
        self._max_tokens = max_tokens
        # Share the upstream limit across diagnosis, dialogue and form import.
        self._request_slots = asyncio.Semaphore(max(1, settings.max_concurrent_model_calls))

    def _build_payload(self, messages: list[ChatMessage], stream: bool, thinking_level: ThinkingLevel = "off") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [_model_to_dict(msg) for msg in messages],
            "temperature": self._temperature,
            "top_p": self._top_p,
            "max_tokens": self._max_tokens,
        }
        if stream:
            payload["stream"] = True
        if self._base_url.startswith("https://chat.ecnu.edu.cn/") and self.model_name in {"ecnu-max", "ecnu-plus"}:
            payload["thinking"] = {"type": "disabled" if thinking_level == "off" else "enabled"}
            if thinking_level != "off":
                levels = {"low": "low", "high": "high", "max": "max"} if self.model_name == "ecnu-max" else {"low": "low", "high": "medium", "max": "xhigh"}
                payload["reasoning_effort"] = levels[thinking_level]
                # Leave sampling parameters to the reasoning model's defaults.
                payload.pop("temperature")
                payload.pop("top_p")
                payload["max_tokens"] = max(self._max_tokens, settings.thinking_max_tokens)
        return payload

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def generate(self, messages: list[ChatMessage], *, thinking_level: ThinkingLevel = "off") -> str:
        endpoint = f"{self._base_url}/chat/completions"
        payload = self._build_payload(messages=messages, stream=False, thinking_level=thinking_level)
        headers = self._build_headers()
        async with self._request_slots:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Invalid model response: {data}") from exc

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Empty response from model provider")
        return content.strip()

    async def generate_stream(self, messages: list[ChatMessage], *, thinking_level: ThinkingLevel = "off") -> AsyncIterator[str]:
        endpoint = f"{self._base_url}/chat/completions"
        payload = self._build_payload(messages=messages, stream=True, thinking_level=thinking_level)
        headers = self._build_headers()

        emitted = False
        try:
            async with self._request_slots:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            text = line.strip()
                            if not text or not text.startswith("data:"):
                                continue
                            data_chunk = text[5:].strip()
                            if data_chunk == "[DONE]":
                                break
                            try:
                                chunk_json = json.loads(data_chunk)
                            except json.JSONDecodeError:
                                continue
                            # Some gateways send usage/metadata with choices=[].
                            choices = chunk_json.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {}).get("content", "")
                            if isinstance(delta, str) and delta:
                                emitted = True
                                yield delta
        except httpx.HTTPStatusError:
            # Retrying authentication/quota errors would waste another request.
            raise
        except Exception:
            if emitted:
                # Do not append a second answer after a partially received stream.
                raise
            logger.warning("Streaming is unavailable on provider side, fallback to non-stream response")
            text = await self.generate(messages, thinking_level=thinking_level)
            if text:
                yield text


def _load_example_text() -> tuple[str, str]:
    example_path = Path(__file__).resolve().parent.parent / "example.json"
    if not example_path.exists():
        return "", ""
    try:
        data = json.loads(example_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", ""
    instruction = str(data.get("instruction", ""))[:260]
    output = str(data.get("output", ""))[:260]
    return instruction, output


def _normalize_dialogue_output(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        return "已收到信息。请继续补充目前最困扰你的症状、持续时间以及加重/缓解因素。"
    return text


def _build_independent_dialogue_system_prompt() -> str:
    return (
        "你是医院内网使用的中医颈椎病对话助手。"
        "你面向患者进行连续问诊，目标是逐步补全病史信息。"
        "每轮回答遵循以下规则："
        "1) 先简短复述已知信息；"
        "2) 再给出1-3个最关键的下一步问诊问题；"
        "3) 语气专业、克制，避免绝对化结论；"
        "4) 若信息不足，不给最终治疗方案，而是继续问诊；"
        "5) 优先围绕中医颈椎病常见要点追问：疼痛部位与放射范围、持续时间、"
        "加重/缓解因素、上肢麻木无力、头晕、睡眠与舌脉等。"
    )


def _build_workspace_dialogue_system_prompt() -> str:
    return (
        "你是医院内网工作台中的AI问诊协同助手。"
        "你每轮都会收到“当前病历信息”和“本轮医生追问”。"
        "回答时必须严格依据当前病历，不得编造未提供的信息。"
        "每轮回答遵循以下规则："
        "1) 先用1-2句总结与本轮追问相关的已知病历要点；"
        "2) 再给出1-3个建议追问方向或鉴别要点；"
        "3) 信息缺失时明确指出缺失项（例如病程时长、诱因、神经体征、舌脉等）；"
        "4) 语气专业克制，不直接下最终诊断结论，不输出确定性治疗方案。"
    )


def _build_diagnosis_system_prompt() -> str:
    return (
        "你是医院内网使用的颈椎病中医辅助诊疗助手。"
        "你只能基于“当前这一次用户输入”的信息作答，禁止引用示例、禁止套用默认病例、禁止臆测。"
        "你必须且只允许按以下格式输出，不得增加其它标题、前缀或结尾：\n"
        "西医诊断：...\n"
        "主证：...\n"
        "兼证：...\n"
        "方药：...\n"
        "理由：...\n"
        "其中“方药”必须写出具体处方及每味药的剂量，剂量单位统一使用g；"
        "并给出基本用法用量（例如“每日1剂，分2次温服”）。"
        "当信息不足时，西医诊断/主证/兼证/方药必须输出“未明确”；"
        "理由必须明确写“信息不足，需补充xxx（缺失要点）”。"
        "不得因为经验或示例而给出确定性诊断。"
    )


def _build_openai_compat_provider(
    *,
    base_url: str,
    api_key: str,
    model: str,
    provider_name: str,
) -> LLMProvider:
    if not base_url:
        raise RuntimeError(f"{provider_name} base url is empty")
    logger.info("Using %s provider: model=%s base=%s", provider_name, model, base_url)
    return OpenAICompatibleProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=settings.request_timeout_seconds,
        temperature=settings.generation_temperature,
        top_p=settings.generation_top_p,
        max_tokens=settings.generation_max_tokens,
    )


def build_provider() -> LLMProvider:
    provider = settings.model_provider.lower().strip()

    if provider in {"vllm", "vllm_openai"}:
        return _build_openai_compat_provider(
            base_url=settings.vllm_api_base,
            api_key=settings.vllm_api_key,
            model=settings.vllm_model,
            provider_name="vLLM(OpenAI-compatible)",
        )

    if provider == "openai_compat":
        return _build_openai_compat_provider(
            base_url=settings.openai_api_base,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            provider_name="openai_compat",
        )

    logger.info("Using stub provider, reply will be fixed string 'test'")
    return StubLLMProvider()


class ChatService:
    def __init__(
        self,
        provider: LLMProvider,
        store: InMemorySessionStore,
        system_prompt: str,
        output_formatter: Callable[[str], str],
        max_concurrent_calls: int,
        timeout_seconds: int,
        max_history_messages: int,
    ) -> None:
        self._provider = provider
        self._store = store
        self._system_prompt_text = system_prompt
        self._system_prompt = ChatMessage(role="system", content=system_prompt)
        self._output_formatter = output_formatter
        self._semaphore = asyncio.Semaphore(max_concurrent_calls)
        self._timeout_seconds = timeout_seconds
        self._max_history_messages = max_history_messages

    @property
    def system_prompt_text(self) -> str:
        return self._system_prompt_text

    async def chat(self, request: ChatRequest) -> ChatResponse:
        session_id = request.session_id or uuid.uuid4().hex
        state = await self._store.get_or_create(session_id)
        clean_message = request.message.strip()
        if not clean_message:
            raise HTTPException(status_code=422, detail="message cannot be blank")
        user_message = ChatMessage(role="user", content=clean_message)

        async with state.lock:
            base_history = list(state.history) if request.use_server_history else list(request.history)
            messages = [self._system_prompt, *base_history, user_message]
            start = time.perf_counter()
            try:
                async with self._semaphore:
                    raw_reply = await asyncio.wait_for(
                        self._provider.generate(messages, thinking_level=request.thinking_level),
                        timeout=self._timeout_seconds,
                    )
            except asyncio.TimeoutError as exc:
                raise HTTPException(status_code=504, detail="Model timeout") from exc
            except Exception as exc:
                logger.exception("Model invocation failed")
                raise HTTPException(status_code=502, detail=f"Model call failed: {exc}") from exc

            latency_ms = int((time.perf_counter() - start) * 1000)
            reply_text = self._output_formatter(raw_reply)
            assistant_message = ChatMessage(role="assistant", content=reply_text)
            merged_history = [*base_history, user_message, assistant_message]
            trimmed_history = merged_history[-self._max_history_messages :]

            if request.use_server_history:
                state.history = trimmed_history
                state.last_access = time.time()

            return ChatResponse(
                session_id=session_id,
                reply=reply_text,
                model=self._provider.model_name,
                latency_ms=latency_ms,
                history=trimmed_history,
                thinking_level=request.thinking_level,
            )

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[dict[str, Any]]:
        session_id = request.session_id or uuid.uuid4().hex
        state = await self._store.get_or_create(session_id)
        clean_message = request.message.strip()
        if not clean_message:
            yield {"type": "error", "detail": "message cannot be blank"}
            return
        user_message = ChatMessage(role="user", content=clean_message)

        async with state.lock:
            base_history = list(state.history) if request.use_server_history else list(request.history)
            messages = [self._system_prompt, *base_history, user_message]
            start = time.perf_counter()
            chunks: list[str] = []

            try:
                async with self._semaphore:
                    async for delta in self._provider.generate_stream(messages, thinking_level=request.thinking_level):
                        if not delta:
                            continue
                        chunks.append(delta)
                        yield {"type": "token", "delta": delta}
            except Exception as exc:
                logger.exception("Model stream invocation failed")
                yield {"type": "error", "detail": f"Model call failed: {exc}"}
                return

            latency_ms = int((time.perf_counter() - start) * 1000)
            raw_reply = "".join(chunks).strip()
            if not raw_reply:
                try:
                    async with self._semaphore:
                        raw_reply = await asyncio.wait_for(
                            self._provider.generate(messages, thinking_level=request.thinking_level),
                            timeout=self._timeout_seconds,
                        )
                except Exception as exc:
                    yield {"type": "error", "detail": f"Model call failed: {exc}"}
                    return

            reply_text = self._output_formatter(raw_reply)
            assistant_message = ChatMessage(role="assistant", content=reply_text)
            merged_history = [*base_history, user_message, assistant_message]
            trimmed_history = merged_history[-self._max_history_messages :]

            if request.use_server_history:
                state.history = trimmed_history
                state.last_access = time.time()

            yield {
                "type": "done",
                "thinking_level": request.thinking_level,
                "session_id": session_id,
                "reply": reply_text,
                "model": self._provider.model_name,
                "latency_ms": latency_ms,
                "history": [_model_to_dict(msg) for msg in trimmed_history],
            }


class FormAutofillService:
    def __init__(
        self,
        provider: LLMProvider,
        timeout_seconds: int,
        max_concurrent_calls: int,
    ) -> None:
        self._provider = provider
        self._system_prompt = ChatMessage(role="system", content=FORM_IMPORT_SYSTEM_PROMPT)
        self._timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent_calls)

    async def autofill(self, request: FormAutofillRequest) -> FormAutofillResponse:
        source_text = request.source_text.strip()
        if not source_text:
            raise HTTPException(status_code=422, detail="source_text cannot be blank")

        messages = [self._system_prompt, ChatMessage(role="user", content=source_text)]
        start = time.perf_counter()
        raw_reply = ""

        try:
            async with self._semaphore:
                raw_reply = await asyncio.wait_for(
                    self._provider.generate(messages, thinking_level=request.thinking_level),
                    timeout=self._timeout_seconds,
                )
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=504, detail="Model timeout") from exc
        except Exception as exc:
            logger.exception("Model autofill invocation failed")
            raise HTTPException(status_code=502, detail=f"Model call failed: {exc}") from exc

        return self._build_response(raw_reply, request, start)

    def _build_response(self, raw_reply: str, request: FormAutofillRequest, start: float) -> FormAutofillResponse:
        source_text = request.source_text.strip()
        latency_ms = int((time.perf_counter() - start) * 1000)
        model_payload = _normalize_form_autofill_data(_extract_json_object(raw_reply), source_text)
        heuristic_payload = _build_heuristic_form_autofill_data(source_text)
        merged_payload = _merge_form_autofill_data(model_payload, heuristic_payload, source_text)

        return FormAutofillResponse(
            data=FormAutofillData(**merged_payload),
            model=self._provider.model_name,
            latency_ms=latency_ms,
            raw_reply=(raw_reply or "").strip(),
            thinking_level=request.thinking_level,
        )

    async def autofill_stream(self, request: FormAutofillRequest) -> AsyncIterator[dict[str, Any]]:
        source_text = request.source_text.strip()
        if not source_text:
            yield {"type": "error", "detail": "请填写病例"}
            return
        messages = [self._system_prompt, ChatMessage(role="user", content=source_text)]
        start = time.perf_counter()
        deadline = asyncio.get_running_loop().time() + self._timeout_seconds
        raw_reply = ""
        emitted: dict[str, str] = {}
        yield {"type": "status", "phase": "thinking" if request.thinking_level != "off" else "recognizing"}
        try:
            async with self._semaphore:
                stream = self._provider.generate_stream(messages, thinking_level=request.thinking_level)
                try:
                    while True:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise asyncio.TimeoutError()
                        try:
                            delta = await asyncio.wait_for(stream.__anext__(), timeout=remaining)
                        except StopAsyncIteration:
                            break
                        raw_reply += delta
                        completed = _extract_complete_json_fields(raw_reply)
                        normalized = _normalize_form_autofill_data(completed, source_text)
                        for key in completed:
                            value = normalized[key]
                            if value and value != emitted.get(key):
                                emitted[key] = value
                                yield {"type": "field", "field": key, "value": value}
                finally:
                    await stream.aclose()
            response = self._build_response(raw_reply, request, start)
            # Include normalization corrections and labeled-source fallback fields.
            for key, value in _model_to_dict(response.data).items():
                if value and value != emitted.get(key):
                    emitted[key] = value
                    yield {"type": "field", "field": key, "value": value}
            yield {"type": "done", **_model_to_dict(response)}
        except asyncio.TimeoutError:
            yield {"type": "error", "detail": "识别超时，请重试"}
        except Exception:
            logger.exception("Model autofill stream invocation failed")
            yield {"type": "error", "detail": "识别连接中断，请重试"}


provider = build_provider()

diagnosis_store = InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)
dialogue_store = InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)
workspace_dialogue_store = InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)

diagnosis_service = ChatService(
    provider=provider,
    store=diagnosis_store,
    system_prompt=_build_diagnosis_system_prompt(),
    output_formatter=_normalize_output_format,
    max_concurrent_calls=settings.max_concurrent_model_calls,
    timeout_seconds=settings.request_timeout_seconds,
    max_history_messages=settings.max_history_messages,
)

dialogue_service = ChatService(
    provider=provider,
    store=dialogue_store,
    system_prompt=_build_independent_dialogue_system_prompt(),
    output_formatter=_normalize_dialogue_output,
    max_concurrent_calls=settings.max_concurrent_model_calls,
    timeout_seconds=settings.request_timeout_seconds,
    max_history_messages=settings.max_history_messages,
)

workspace_dialogue_service = ChatService(
    provider=provider,
    store=workspace_dialogue_store,
    system_prompt=_build_workspace_dialogue_system_prompt(),
    output_formatter=_normalize_dialogue_output,
    max_concurrent_calls=settings.max_concurrent_model_calls,
    timeout_seconds=settings.request_timeout_seconds,
    max_history_messages=settings.max_history_messages,
)

form_autofill_service = FormAutofillService(
    provider=provider,
    timeout_seconds=settings.request_timeout_seconds,
    max_concurrent_calls=settings.max_concurrent_model_calls,
)

app = FastAPI(title="Hospital Intranet Chat System", version="0.6.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

web_dir = Path(__file__).resolve().parent / "web"
app.mount("/static", StaticFiles(directory=web_dir), name="static")

_cleanup_task: asyncio.Task | None = None


@app.middleware("http")
async def _disable_static_cache(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path in {"/", "/dialogue", "/diagnosis", "/favicon.ico"} or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(settings.session_cleanup_interval_seconds)
        removed_diagnosis = await diagnosis_store.cleanup_expired()
        removed_dialogue = await dialogue_store.cleanup_expired()
        removed_workspace_dialogue = await workspace_dialogue_store.cleanup_expired()
        total_removed = removed_diagnosis + removed_dialogue + removed_workspace_dialogue
        if total_removed:
            logger.info(
                "Cleaned up %s expired sessions (diagnosis=%s, dialogue=%s, workspace_dialogue=%s)",
                total_removed,
                removed_diagnosis,
                removed_dialogue,
                removed_workspace_dialogue,
            )


@app.on_event("startup")
async def _on_startup() -> None:
    global _cleanup_task
    _cleanup_task = asyncio.create_task(_cleanup_loop())


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    if _cleanup_task is None:
        return
    _cleanup_task.cancel()
    try:
        await _cleanup_task
    except asyncio.CancelledError:
        pass


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(web_dir / "diagnosis.html")


@app.get("/dialogue", include_in_schema=False)
async def dialogue_page() -> FileResponse:
    return FileResponse(web_dir / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> RedirectResponse:
    return RedirectResponse(url="/static/favicon.svg", status_code=307)


@app.get("/diagnosis", include_in_schema=False)
async def diagnosis_page() -> FileResponse:
    return FileResponse(web_dir / "diagnosis.html")


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    diagnosis_sessions = await diagnosis_store.active_sessions()
    dialogue_sessions = await dialogue_store.active_sessions()
    workspace_dialogue_sessions = await workspace_dialogue_store.active_sessions()
    return HealthResponse(
        status="ok",
        provider=provider.model_name,
        active_sessions=diagnosis_sessions + dialogue_sessions + workspace_dialogue_sessions,
        max_concurrent_model_calls=settings.max_concurrent_model_calls,
    )


@app.get("/api/prompt", response_model=PromptResponse)
async def prompt() -> PromptResponse:
    return PromptResponse(
        system_prompt=diagnosis_service.system_prompt_text,
        required_output_format=OUTPUT_TEMPLATE,
    )


@app.get("/api/dialogue/prompt", response_model=PromptResponse)
async def dialogue_prompt() -> PromptResponse:
    return PromptResponse(
        system_prompt=dialogue_service.system_prompt_text,
        required_output_format="对话追问模式（无固定字段模板）",
    )


@app.get("/api/workspace/prompt", response_model=PromptResponse)
async def workspace_prompt() -> PromptResponse:
    return PromptResponse(
        system_prompt=workspace_dialogue_service.system_prompt_text,
        required_output_format="工作台协同追问模式（读取当前病历）",
    )


@app.post("/api/form/autofill", response_model=FormAutofillResponse)
async def form_autofill(request: FormAutofillRequest) -> FormAutofillResponse:
    return await form_autofill_service.autofill(request)


@app.post("/api/form/autofill/stream")
async def form_autofill_stream(request: FormAutofillRequest) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        async for event in form_autofill_service.autofill_stream(request):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await diagnosis_service.chat(request)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        async for event in diagnosis_service.chat_stream(request):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/dialogue/chat", response_model=ChatResponse)
async def dialogue_chat(request: ChatRequest) -> ChatResponse:
    return await dialogue_service.chat(request)


@app.post("/api/dialogue/chat/stream")
async def dialogue_chat_stream(request: ChatRequest) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        async for event in dialogue_service.chat_stream(request):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/workspace/chat", response_model=ChatResponse)
async def workspace_chat(request: ChatRequest) -> ChatResponse:
    return await workspace_dialogue_service.chat(request)


@app.post("/api/workspace/chat/stream")
async def workspace_chat_stream(request: ChatRequest) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        async for event in workspace_dialogue_service.chat_stream(request):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/session/reset")
async def reset_session(request: ResetSessionRequest) -> dict[str, object]:
    cleared = await diagnosis_store.clear(request.session_id)
    return {"session_id": request.session_id, "cleared": cleared}


@app.post("/api/dialogue/session/reset")
async def reset_dialogue_session(request: ResetSessionRequest) -> dict[str, object]:
    cleared = await dialogue_store.clear(request.session_id)
    return {"session_id": request.session_id, "cleared": cleared}


@app.post("/api/workspace/session/reset")
async def reset_workspace_session(request: ResetSessionRequest) -> dict[str, object]:
    cleared = await workspace_dialogue_store.clear(request.session_id)
    return {"session_id": request.session_id, "cleared": cleared}
