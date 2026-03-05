# 医院内网对话系统（颈椎病辅疗）

当前已支持三种模型接入方式：
- `vllm_openai`（推荐）：应用服务通过 HTTP 调用 vLLM，彻底解耦大模型进程
- `openai_compat`：调用任意 OpenAI 兼容网关
- `hf_local`：应用进程内直接加载 HuggingFace 模型（仅作为备用）

## 1. 为什么用 vLLM 解耦

`vLLM` 作为独立模型服务，应用层只负责业务逻辑与对话接口：
- 应用服务崩溃不会直接拖垮模型进程
- 模型服务可单独扩缩容与调优
- 更适合后续做多应用共享同一模型网关

当前默认配置已经切到 `MODEL_PROVIDER=vllm_openai`。

## 2. 启动顺序（推荐）

先启动 vLLM，再启动本项目。

### 2.1 安装应用依赖

```bash
cd hospital_chat_system
pip install -r requirements.txt
```

### 2.2 安装 vLLM 依赖（Linux + CUDA）

```bash
pip install -r requirements.vllm.txt
```

### 2.3 启动 vLLM 服务

脚本：

```bash
bash scripts/start_vllm_server.sh
```

如果出现类似报错：
`Free memory ... is less than desired GPU memory utilization`
请降低显存利用率或上下文长度，例如：

```bash
export VLLM_GPU_MEMORY_UTILIZATION=0.85
export VLLM_MAX_MODEL_LEN=4096
bash scripts/start_vllm_server.sh
```

若仍不稳定，可再加：

```bash
export VLLM_ENFORCE_EAGER=1
bash scripts/start_vllm_server.sh
```

等价命令（示例）：

```bash
python -m vllm.entrypoints.openai.api_server \
  --host 0.0.0.0 \
  --port 8001 \
  --model /home/lwb/Decoding/mydecoding/mydecoding/base_model/qwen/Qwen2___5-7B-Instruct \
  --served-model-name qwen2.5-7b-instruct \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.9 \
  --max-model-len 8192 \
  --dtype bfloat16
```

### 2.4 启动应用服务

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

访问：
- `http://服务器IP:8000`

## 3. workers 参数建议

`uvicorn --workers N` 是应用进程数，不是 vLLM 的并发线程数。

在 vLLM 解耦模式下：
- 可以按 CPU 和业务并发需求增加应用 worker
- 但建议先从 `--workers 1` 起步，确认稳定后再逐步增大

在 `hf_local` 模式下：
- 每个 worker 都会加载一份模型，显存会叠加
- 通常只能 `--workers 1`

## 4. 关键环境变量

`.env` 默认值已可直接用于 vLLM 解耦模式：

```env
MODEL_PROVIDER=vllm_openai
VLLM_API_BASE=http://127.0.0.1:8001/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=qwen2.5-7b-instruct

GENERATION_TEMPERATURE=0.2
GENERATION_TOP_P=0.9
GENERATION_MAX_TOKENS=512
```

## 5. 已提供接口

- `GET /api/health`
- `POST /api/chat`
- `POST /api/session/reset`

`/api/chat` 请求示例：

```json
{
  "session_id": "abc123",
  "message": "患者颈痛1年，左上肢麻木1周",
  "history": [],
  "use_server_history": false
}
```
