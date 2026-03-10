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

    # Runtime
    request_timeout_seconds: int = _int_env("REQUEST_TIMEOUT_SECONDS", 120)
    max_concurrent_model_calls: int = _int_env("MAX_CONCURRENT_MODEL_CALLS", 200)
    max_history_messages: int = _int_env("MAX_HISTORY_MESSAGES", 20)
    session_ttl_seconds: int = _int_env("SESSION_TTL_SECONDS", 3600)
    session_cleanup_interval_seconds: int = _int_env("SESSION_CLEANUP_INTERVAL_SECONDS", 300)


settings = Settings()


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128)
    history: list[ChatMessage] = Field(default_factory=list)
    use_server_history: bool = True


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    model: str
    latency_ms: int
    history: list[ChatMessage]


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

    async def generate(self, messages: list[ChatMessage]) -> str:
        pass

    async def generate_stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        pass


class StubLLMProvider:
    model_name = "stub-test"

    async def generate(self, messages: list[ChatMessage]) -> str:
        await asyncio.sleep(0.02)
        return "西医诊断：test\n主证：test\n兼证：test\n方药：test\n理由：test"

    async def generate_stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        text = await self.generate(messages)
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

    def _build_payload(self, messages: list[ChatMessage], stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [_model_to_dict(msg) for msg in messages],
            "temperature": self._temperature,
            "top_p": self._top_p,
            "max_tokens": self._max_tokens,
        }
        if stream:
            payload["stream"] = True
        return payload

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def generate(self, messages: list[ChatMessage]) -> str:
        endpoint = f"{self._base_url}/chat/completions"
        payload = self._build_payload(messages=messages, stream=False)
        headers = self._build_headers()
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

    async def generate_stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        endpoint = f"{self._base_url}/chat/completions"
        payload = self._build_payload(messages=messages, stream=True)
        headers = self._build_headers()

        try:
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
                        delta = (
                            chunk_json.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if isinstance(delta, str) and delta:
                            yield delta
        except Exception:
            logger.warning("Streaming is unavailable on provider side, fallback to non-stream response")
            text = await self.generate(messages)
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


def _build_dialogue_system_prompt() -> str:
    return (
        "你是医院内网使用的颈椎病问诊助手。"
        "你的目标是通过连续追问完成结构化病史采集。"
        "每轮回答遵循以下规则："
        "1) 先简短复述已知信息；"
        "2) 再给出1-3个最关键的下一步问诊问题；"
        "3) 语气专业、克制，避免绝对化结论；"
        "4) 若信息不足，不给最终治疗方案，而是继续问诊。"
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
                        self._provider.generate(messages),
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
                    async for delta in self._provider.generate_stream(messages):
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
                            self._provider.generate(messages),
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
                "session_id": session_id,
                "reply": reply_text,
                "model": self._provider.model_name,
                "latency_ms": latency_ms,
                "history": [_model_to_dict(msg) for msg in trimmed_history],
            }


provider = build_provider()

diagnosis_store = InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)
dialogue_store = InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)

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
    system_prompt=_build_dialogue_system_prompt(),
    output_formatter=_normalize_dialogue_output,
    max_concurrent_calls=settings.max_concurrent_model_calls,
    timeout_seconds=settings.request_timeout_seconds,
    max_history_messages=settings.max_history_messages,
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
    if path in {"/", "/diagnosis", "/favicon.ico"} or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(settings.session_cleanup_interval_seconds)
        removed_diagnosis = await diagnosis_store.cleanup_expired()
        removed_dialogue = await dialogue_store.cleanup_expired()
        total_removed = removed_diagnosis + removed_dialogue
        if total_removed:
            logger.info(
                "Cleaned up %s expired sessions (diagnosis=%s, dialogue=%s)",
                total_removed,
                removed_diagnosis,
                removed_dialogue,
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
    return HealthResponse(
        status="ok",
        provider=provider.model_name,
        active_sessions=diagnosis_sessions + dialogue_sessions,
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


@app.post("/api/session/reset")
async def reset_session(request: ResetSessionRequest) -> dict[str, object]:
    cleared = await diagnosis_store.clear(request.session_id)
    return {"session_id": request.session_id, "cleared": cleared}


@app.post("/api/dialogue/session/reset")
async def reset_dialogue_session(request: ResetSessionRequest) -> dict[str, object]:
    cleared = await dialogue_store.clear(request.session_id)
    return {"session_id": request.session_id, "cleared": cleared}
