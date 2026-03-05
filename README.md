# 医院内网对话系统（颈椎病辅疗）

本项目已实现：
- 无登录注册的网页对话
- `/api/chat` 对话接口
- 本地模型直连（`transformers`）
- OpenAI 兼容网关接入
- 占位模式（返回 `test`）

## 1. workers 参数说明

`uvicorn --workers N` 表示启动 `N` 个独立进程。

作用：
- 提升并发处理能力（多个请求可由不同进程并行处理）
- 避免单进程阻塞导致整体卡顿

注意：
- 如果使用本地大模型（如 Qwen2.5-7B）并加载在 GPU 上，每个 worker 都会各自加载一份模型。
- 这会导致显存占用按 worker 数量叠加，通常会直接 OOM。
- 因此本地单卡模型建议 `--workers 1`。

## 2. 本地 Qwen 路径接入

你提供的模型路径：

`/home/lwb/Decoding/mydecoding/mydecoding/base_model/qwen/Qwen2___5-7B-Instruct`

### 2.1 安装依赖

```bash
cd hospital_chat_system
pip install -r requirements.txt
pip install -r requirements.local_model.txt
```

如果你需要 CUDA 版 PyTorch，建议按官方命令安装匹配版本，再安装其余依赖。

### 2.2 配置环境变量

复制模板：

```bash
cp .env.example .env
```

关键项应为：

```env
MODEL_PROVIDER=hf_local
LOCAL_MODEL_PATH=/home/lwb/Decoding/mydecoding/mydecoding/base_model/qwen/Qwen2___5-7B-Instruct
LOCAL_MODEL_DTYPE=bfloat16
LOCAL_MODEL_DEVICE_MAP=auto
LOCAL_MODEL_MAX_PARALLEL=1
```

### 2.3 启动服务（本地模型建议）

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

访问：
- `http://127.0.0.1:8000`

## 3. 已实现接口

- `GET /api/health`
- `POST /api/chat`
- `POST /api/session/reset`

`/api/chat` 请求体示例：

```json
{
  "session_id": "abc123",
  "message": "患者颈痛1年，左上肢麻木1周",
  "history": [],
  "use_server_history": false
}
```

## 4. 提供器模式

- `MODEL_PROVIDER=hf_local`：直接加载本地 HuggingFace 模型路径
- `MODEL_PROVIDER=openai_compat`：走 OpenAI 兼容网关
- `MODEL_PROVIDER=stub`：返回 `test`

