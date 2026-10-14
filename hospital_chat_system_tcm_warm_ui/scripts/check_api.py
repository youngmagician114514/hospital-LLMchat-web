"""Call the configured backend with synthetic text. Never print credentials."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ['MODEL_PROVIDER'] = 'openai_compat'
import app
import httpx


async def check():
    messages = [app.ChatMessage(role='user', content='接口连通性测试，请仅回复：连接正常。')]
    start = time.perf_counter()
    reply = await app.provider.generate(messages)
    checks = [{'check': 'non_stream', 'passed': bool(reply.strip()), 'reply': reply, 'elapsed_ms': round((time.perf_counter()-start)*1000)}]
    parts = [part async for part in app.provider.generate_stream(messages)]
    checks.append({'check': 'stream', 'passed': bool(parts) and bool(''.join(parts).strip()), 'chunks': len(parts), 'reply': ''.join(parts)})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url='http://local-check') as client:
        response = await client.post('/api/chat/stream', json={
            'message': '软件接口测试，未提供任何患者信息。诊断、主证、兼证和方药应为未明确，理由说明未提供病历。',
            'session_id': 'api-connection-test', 'history': [], 'use_server_history': False,
        })
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        done = next((event for event in events if event.get('type') == 'done'), None)
        checks.append({'check': 'diagnosis_endpoint', 'passed': response.status_code == 200 and bool(done) and all(label+'：' in done['reply'] for label in app.OUTPUT_LABELS), 'model': done.get('model') if done else None})
        response = await client.post('/api/form/autofill', json={'source_text': '以下为虚构的软件测试记录：性别：女。年龄：45岁。主诉：测试占位内容。现病史：待填写。无真实患者资料。'})
        data = response.json() if response.status_code == 200 else {}
        checks.append({'check': 'form_autofill', 'passed': response.status_code == 200 and data.get('data', {}).get('patientGender') == '女' and data.get('data', {}).get('patientAge') == '45', 'model': data.get('model')})
    print(json.dumps({'model': app.provider.model_name, 'checks': checks}, ensure_ascii=False, indent=2))
    assert all(item['passed'] for item in checks), 'API verification failed'


if __name__ == '__main__':
    try:
        asyncio.run(check())
    except httpx.HTTPStatusError as exc:
        print(f'Upstream HTTP error: {exc.response.status_code}; check token, model access and quota.')
        sys.exit(1)
