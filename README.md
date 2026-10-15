# 颈椎病中医辅助诊疗系统

当前工作台源码位于 `hospital_chat_system_tcm_warm_ui/`。

## 启动

在 Windows PowerShell 中进入源码目录并安装依赖：

```powershell
cd hospital_chat_system_tcm_warm_ui
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中填写模型服务的 API Key，然后运行：

```powershell
.\scripts\start_app.cmd
```

打开 <http://127.0.0.1:8765/diagnosis>。默认模型为 `ecnu-max`，思考强度可在页面顶部切换。

## 功能与目录

- 病例录入与识别填充、结构化诊断建议、工作台问诊助手及独立问诊。
- 各入口支持流式返回和连续文字显示。
- `hospital_chat_system_tcm_warm_ui/app.py`：FastAPI 服务。
- `hospital_chat_system_tcm_warm_ui/web/`：网页界面。
- `hospital_chat_system_tcm_warm_ui/scripts/`：启动与检查脚本。
- `hospital_chat_system_tcm_warm_ui/tests/`：后端与流式显示回归检查。

完整配置与接口说明见 [工作台 README](hospital_chat_system_tcm_warm_ui/README.md)。本地配置、病例资料和模型文件由 `.gitignore` 排除。

## 检查

在源码目录运行：

```powershell
python -m unittest discover -s tests -v
node tests/test_streaming_ui.cjs
```
