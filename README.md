# 医院内网对话系统（颈椎病辅疗）

当前支持两种模型接入方式：
- `vllm_openai`：通过 OpenAI 兼容协议调用 vLLM（推荐内网部署）
- `openai_compat`：通过 OpenAI 兼容协议调用外部模型网关（如阿里云百炼）

## 1. workers 在 vLLM 解耦下的作用

`uvicorn --workers N` 控制的是应用服务进程数，不是 vLLM 的工作进程数。

在 vLLM 解耦架构下：
- 应用层 worker 负责 HTTP 接入、会话管理、请求转发
- 模型吞吐主要由 vLLM 端调度和显存配置决定
- 增加应用 worker 能提升连接处理能力，但不会线性提升模型生成速度

建议：
- 先 `--workers 1` 验证稳定性
- 再按 CPU 与并发压测逐步提升到 `2~4`

## 2. 外部 API（百炼）配置

编辑 `.env`：

```env
MODEL_PROVIDER=openai_compat
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=your-dashscope-api-key
OPENAI_MODEL=qwen-plus
```

启动：

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

## 3. vLLM 解耦配置

编辑 `.env`：

```env
MODEL_PROVIDER=vllm_openai
VLLM_API_BASE=http://127.0.0.1:8001/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=qwen2.5-7b-instruct
```

先启动 vLLM：

```bash
bash scripts/start_vllm_server.sh
```

再启动应用：

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

## 4. 输出格式约束

系统会强制输出为以下固定结构：

```text
西医诊断：
主证：
兼证：
方药：
理由：
```

即使模型返回不规范文本，后端也会自动归一化为该格式。

## 5. API 接口

- `GET /api/health`
- `GET /api/prompt`（展示系统提示词）
- `POST /api/chat`（普通请求）
- `POST /api/chat/stream`（SSE 流式输出）
- `POST /api/session/reset`

