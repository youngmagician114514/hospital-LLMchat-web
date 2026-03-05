from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("hospital-chat")


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

    # vLLM decoupled config (recommended for production)
    vllm_api_base: str = os.getenv("VLLM_API_BASE", "http://127.0.0.1:8001/v1").strip()
    vllm_api_key: str = os.getenv("VLLM_API_KEY", "").strip()
    vllm_model: str = os.getenv("VLLM_MODEL", "qwen2.5-7b-instruct").strip()

    # Shared inference params for OpenAI-compatible backends
    generation_temperature: float = _float_env("GENERATION_TEMPERATURE", 0.2)
    generation_top_p: float = _float_env("GENERATION_TOP_P", 0.9)
    generation_max_tokens: int = _int_env("GENERATION_MAX_TOKENS", 512)

    # Local HF model mode (optional fallback)
    local_model_path: str = os.getenv("LOCAL_MODEL_PATH", "").strip()
    local_model_dtype: str = os.getenv("LOCAL_MODEL_DTYPE", "bfloat16").strip().lower()
    local_model_device_map: str = os.getenv("LOCAL_MODEL_DEVICE_MAP", "auto").strip()
    local_model_max_new_tokens: int = _int_env("LOCAL_MODEL_MAX_NEW_TOKENS", 512)
    local_model_temperature: float = _float_env("LOCAL_MODEL_TEMPERATURE", 0.2)
    local_model_top_p: float = _float_env("LOCAL_MODEL_TOP_P", 0.9)
    local_model_repetition_penalty: float = _float_env("LOCAL_MODEL_REPETITION_PENALTY", 1.05)
    local_model_max_parallel: int = _int_env("LOCAL_MODEL_MAX_PARALLEL", 1)

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


def _model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


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


class StubLLMProvider:
    model_name = "stub-test"

    async def generate(self, messages: list[ChatMessage]) -> str:
        await asyncio.sleep(0.02)
        return "test"


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

    async def generate(self, messages: list[ChatMessage]) -> str:
        endpoint = f"{self._base_url}/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": [_model_to_dict(msg) for msg in messages],
            "temperature": self._temperature,
            "top_p": self._top_p,
            "max_tokens": self._max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

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


class LocalTransformersProvider:
    def __init__(
        self,
        model_path: str,
        dtype: str,
        device_map: str,
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        repetition_penalty: float,
        max_parallel: int,
    ) -> None:
        self._model_path = Path(model_path)
        if not self._model_path.exists():
            raise RuntimeError(f"LOCAL_MODEL_PATH does not exist: {self._model_path}")

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except Exception as exc:
            raise RuntimeError(
                "Local model provider requires torch and transformers. "
                "Install dependencies first."
            ) from exc

        self._torch = torch
        self._max_new_tokens = max(1, max_new_tokens)
        self._temperature = max(0.0, temperature)
        self._top_p = min(max(top_p, 0.01), 1.0)
        self._repetition_penalty = max(1.0, repetition_penalty)
        self._parallel_limiter = asyncio.Semaphore(max(1, max_parallel))
        self.model_name = self._model_path.name

        logger.info("Loading local model from %s", self._model_path)
        tokenizer = AutoTokenizer.from_pretrained(
            str(self._model_path),
            trust_remote_code=True,
            use_fast=True,
        )
        if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
            tokenizer.pad_token = tokenizer.eos_token
        self._tokenizer = tokenizer

        model_kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            "device_map": device_map,
        }
        torch_dtype = self._resolve_dtype(dtype, torch)
        if torch_dtype is not None:
            model_kwargs["torch_dtype"] = torch_dtype

        self._model = AutoModelForCausalLM.from_pretrained(str(self._model_path), **model_kwargs)
        self._model.eval()
        logger.info(
            "Local model ready: %s, dtype=%s, device_map=%s, max_parallel=%s",
            self.model_name,
            dtype,
            device_map,
            max(1, max_parallel),
        )

    @staticmethod
    def _resolve_dtype(dtype: str, torch_module: Any) -> Any | None:
        mapping = {
            "auto": None,
            "bfloat16": torch_module.bfloat16,
            "bf16": torch_module.bfloat16,
            "float16": torch_module.float16,
            "fp16": torch_module.float16,
            "float32": torch_module.float32,
            "fp32": torch_module.float32,
        }
        if dtype not in mapping:
            logger.warning("Unknown LOCAL_MODEL_DTYPE=%s, fallback to auto", dtype)
            return None
        return mapping[dtype]

    def _build_prompt(self, messages: list[ChatMessage]) -> str:
        chat_messages = [_model_to_dict(msg) for msg in messages]
        if hasattr(self._tokenizer, "apply_chat_template"):
            return self._tokenizer.apply_chat_template(
                chat_messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        lines = [f"{msg['role']}: {msg['content']}" for msg in chat_messages]
        lines.append("assistant:")
        return "\n".join(lines)

    def _prepare_inputs(self, prompt: str) -> dict[str, Any]:
        inputs = self._tokenizer(prompt, return_tensors="pt")
        try:
            target_device = next(self._model.parameters()).device
        except StopIteration:
            target_device = None
        if target_device is None:
            return dict(inputs)
        return {key: value.to(target_device) for key, value in inputs.items()}

    def _generate_sync(self, messages: list[ChatMessage]) -> str:
        prompt = self._build_prompt(messages)
        inputs = self._prepare_inputs(prompt)
        input_ids = inputs["input_ids"]
        generation_kwargs: dict[str, Any] = {
            "max_new_tokens": self._max_new_tokens,
            "repetition_penalty": self._repetition_penalty,
            "pad_token_id": self._tokenizer.pad_token_id,
            "eos_token_id": self._tokenizer.eos_token_id,
        }
        if self._temperature <= 0:
            generation_kwargs["do_sample"] = False
        else:
            generation_kwargs["do_sample"] = True
            generation_kwargs["temperature"] = self._temperature
            generation_kwargs["top_p"] = self._top_p

        with self._torch.inference_mode():
            output_ids = self._model.generate(**inputs, **generation_kwargs)

        generated_ids = output_ids[0][input_ids.shape[-1] :]
        text = self._tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
        return text if text else "test"

    async def generate(self, messages: list[ChatMessage]) -> str:
        async with self._parallel_limiter:
            return await asyncio.to_thread(self._generate_sync, messages)


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


def _build_system_prompt() -> str:
    instruction_sample, output_sample = _load_example_text()
    prompt = (
        "你是医院内网使用的颈椎病中医辅助诊疗对话助手。"
        "当用户输入病例描述时，优先按“西医诊断、主证、兼证、方药”四部分组织输出。"
        "语气需客观、谨慎，不夸大疗效，不替代医生最终决策。"
    )
    if instruction_sample and output_sample:
        prompt += (
            f" 参考样例输入片段：{instruction_sample}。"
            f" 参考样例输出片段：{output_sample}。"
        )
    return prompt


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

    if provider in {"hf_local", "transformers_local", "local_transformers"}:
        if not settings.local_model_path:
            raise RuntimeError("MODEL_PROVIDER=hf_local but LOCAL_MODEL_PATH is empty.")
        return LocalTransformersProvider(
            model_path=settings.local_model_path,
            dtype=settings.local_model_dtype,
            device_map=settings.local_model_device_map,
            max_new_tokens=settings.local_model_max_new_tokens,
            temperature=settings.local_model_temperature,
            top_p=settings.local_model_top_p,
            repetition_penalty=settings.local_model_repetition_penalty,
            max_parallel=settings.local_model_max_parallel,
        )

    logger.info("Using stub provider, reply will be fixed string 'test'")
    return StubLLMProvider()


class ChatService:
    def __init__(
        self,
        provider: LLMProvider,
        store: InMemorySessionStore,
        system_prompt: str,
        max_concurrent_calls: int,
        timeout_seconds: int,
        max_history_messages: int,
    ) -> None:
        self._provider = provider
        self._store = store
        self._system_prompt = ChatMessage(role="system", content=system_prompt)
        self._semaphore = asyncio.Semaphore(max_concurrent_calls)
        self._timeout_seconds = timeout_seconds
        self._max_history_messages = max_history_messages

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
                    reply = await asyncio.wait_for(
                        self._provider.generate(messages),
                        timeout=self._timeout_seconds,
                    )
            except asyncio.TimeoutError as exc:
                raise HTTPException(status_code=504, detail="Model timeout") from exc
            except Exception as exc:
                logger.exception("Model invocation failed")
                raise HTTPException(status_code=502, detail=f"Model call failed: {exc}") from exc

            latency_ms = int((time.perf_counter() - start) * 1000)
            reply_text = reply.strip() if isinstance(reply, str) else ""
            if not reply_text:
                reply_text = "test"
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


store = InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)
provider = build_provider()
service = ChatService(
    provider=provider,
    store=store,
    system_prompt=_build_system_prompt(),
    max_concurrent_calls=settings.max_concurrent_model_calls,
    timeout_seconds=settings.request_timeout_seconds,
    max_history_messages=settings.max_history_messages,
)

app = FastAPI(title="Hospital Intranet Chat System", version="0.3.0")
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
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(settings.session_cleanup_interval_seconds)
        removed = await store.cleanup_expired()
        if removed:
            logger.info("Cleaned up %s expired sessions", removed)


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


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        provider=provider.model_name,
        active_sessions=await store.active_sessions(),
        max_concurrent_model_calls=settings.max_concurrent_model_calls,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await service.chat(request)


@app.post("/api/session/reset")
async def reset_session(request: ResetSessionRequest) -> dict[str, object]:
    cleared = await store.clear(request.session_id)
    return {"session_id": request.session_id, "cleared": cleared}
