# 颈椎病辅助诊疗工作台

2026-10-14 更新了工作台和独立问诊页的布局、文案与交互，并接入 ChatECNU API。

2026-10-15 简化独立问诊页：空白会话居中输入，开始对话后输入框固定在底部；删除重复说明和回复耗时信息。统一字体体系，正文与输入内容使用 14px，保留桌面病历首屏完整录入。Noto Sans 拉丁字体随项目提供，中文使用系统字体回退，字体许可证见 `web/fonts/OFL.txt`。

## 启动已配置的 ChatECNU

```powershell
.\scripts\start_app.cmd
```

打开 <http://127.0.0.1:8765/diagnosis>。此模式读取本机 `.env` 的 Token，病历导入、生成建议和问诊会调用 ChatECNU。

接口地址是 `https://chat.ecnu.edu.cn/open/api/v1`，默认模型为 `ecnu-max`。配置依据：[官方接入文档](https://developer.ecnu.edu.cn/vitepress/llm/index.html)、[模型与并发限制](https://developer.ecnu.edu.cn/vitepress/llm/model.html)。

页面顶部可切换思考强度：关闭、中、高、超高，默认中；选择保存在本机浏览器，工作台与独立问诊共用。诊断、问诊、病历导入都会随请求传递当前档位。请求进行中暂停切换，结果附带本次使用的档位。

对 `ecnu-max`，中/高/超高对应 `low`/`high`/`max`，关闭使用 `thinking.type=disabled`；开启时使用模型默认采样参数。映射依据：[官方思考模式文档](https://developer.ecnu.edu.cn/vitepress/llm/thinking.html)。思考模式使用 `THINKING_MAX_TOKENS` 设置总输出预算，当前为 8192；普通输出预算保留为 1536。请求超时为 300 秒。

Token 只放在 `.env` 中，浏览器不持有它。工作台、独立问诊与导入共用一个最多 3 请求的上游并发限额。使用一个应用 worker；多 worker 或多台部署时，应增加跨进程限流。

```powershell
# 少量测试请求，验证普通回复、流式回复、诊断与病历导入；不使用本地病例表
python .\scripts\check_api.py

# 使用模拟 HTTP 的回归检查，不调用实际模型
python -m unittest discover -s tests -v
```

## 本机预览（无需模型）

在本目录运行：

```powershell
.\scripts\start_preview.cmd
```

打开 <http://127.0.0.1:8765/diagnosis>。独立问诊页为 <http://127.0.0.1:8765/dialogue>。

该脚本仅在当前进程使用 `MODEL_PROVIDER=stub`，不改写 `.env`。回复是固定的 `test` 文本，用于检查导入、流式显示和复制流程，不代表诊疗能力。按 Ctrl+C 停止预览。可直接双击运行该脚本；如需指定端口，也可使用 `scripts/start_preview.ps1 -Port 8766`。

## 页面操作

- 顶部“独立问诊”右侧的“帮助文档”：快速开始、病历录入、导入与示例、诊断建议、问诊与思考、常见问题与快捷键、版本更新。文档支持目录导航与章节链接，地址为 `/static/help.html`；更新记录为 `/static/help.html?page=changelog`，按日期倒序整理。
- 顶部“导入病历”：粘贴病历原文，识别后替换当前表单；导入后请核对。
- 顶部“示例病例”：打开导入窗口并载入原有示例，点击“识别填充”后才替换表单。导入窗口内的“载入示例”按钮保留。
- 左侧“本次病历”：初诊/复诊、性别、年龄以及六项病历文本，两列显示；常用办公分辨率下无需滚动即可看到全部。
- 左侧“复诊记录”与“图片资料”：切换标签填写；复诊记录在选择复诊后启用。切换标签保留已填写内容。
- 长文本：点击字段旁的“展开”进入大窗口编辑，保存后回填；长内容只在对应文本框内滚动。
- 右侧“诊断建议”：西医诊断、主证、兼证、方药与理由；可复制整份结果或单项内容。生成时自动切换到该标签。
- 右侧“问诊助手”：结合当前病历提问，快捷问题仅填入输入框，点击发送后才发起请求。切换右侧标签保留输入草稿。
- 修改病历后，旧结果标记为“需重新生成”，并禁用复制。请求处理中暂停编辑病历。
- “新建病历”清空当前表单和结果，并开始新的问诊会话。
- Ctrl+Enter 生成建议；问诊输入框 Enter 发送，Shift+Enter 换行。
- 标签支持左右方向键切换；展开编辑窗口中 Ctrl+Enter 保存。

草稿存储在当前浏览器的 `localStorage`，不等同于医院病历归档；图片暂时仅在本机预览。页面已经适配桌面、平板宽度和手机宽度。

## 开发位置

`app.py` 是 FastAPI 服务；`web/diagnosis.html`、`diagnosis.js`、`diagnosis.css` 为工作台；`web/index.html`、`chat.js`、`chat.css` 为独立问诊；`web/help.html`、`help.js`、`help.css` 为帮助文档；`web/theme.css` 提供公共样式。

更完整的目录、历史与待办见上级目录的 `项目梳理_2026-10-14.md`。修改前代码保存在上级 `_review/2026-10-14/warm_ui_before.zip`，其中不含 `.env`。

## 模型接入（保留原有说明）

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

诊断正文在收到首段内容后直接显示，并随流式返回逐段追加；结束后整理为结果卡片，可展开“查看原文”。开启思考时，首段正文之前会有思考等待。

病例识别在导入窗口中逐项展示提取结果，成功后填入病历。识别中断时原病历保留。工作台问诊助手、独立问诊和诊断正文共用连续显示逻辑，快速合并返回的文字也逐步绘制，结束事件不会立即覆盖尚未显示的内容。

## 5. API 接口

- `GET /api/health`
- `GET /api/prompt`（展示系统提示词）
- `POST /api/chat`（普通请求）
- `POST /api/chat/stream`（SSE 流式输出）
- `POST /api/form/autofill/stream`（逐项返回识别字段）
- `POST /api/workspace/chat/stream`（工作台问诊流式输出）
- `POST /api/dialogue/chat/stream`（独立问诊流式输出）
- `POST /api/session/reset`
