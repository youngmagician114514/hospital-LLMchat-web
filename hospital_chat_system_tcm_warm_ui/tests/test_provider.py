"""Regression checks with synthetic responses; never call the configured API."""
import asyncio
from dataclasses import replace
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ['MODEL_PROVIDER'] = 'stub'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import app

REAL_CLIENT = httpx.AsyncClient


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings_patch = patch.object(app, 'settings', replace(app.settings, max_concurrent_model_calls=3))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.provider = app.OpenAICompatibleProvider(
            base_url='https://chat.ecnu.edu.cn/open/api/v1',
            api_key='test-key', model='ecnu-plus', timeout_seconds=5,
            temperature=0.2, top_p=0.9, max_tokens=1536,
        )
        self.messages = [app.ChatMessage(role='user', content='接口测试')]

    def mock_client(self, handler):
        transport = httpx.MockTransport(handler)
        return patch.object(app.httpx, 'AsyncClient', side_effect=lambda **kw: REAL_CLIENT(transport=transport, **kw))

    async def test_compatible_request(self):
        async def handler(request):
            self.assertEqual(str(request.url), 'https://chat.ecnu.edu.cn/open/api/v1/chat/completions')
            self.assertEqual(request.headers['Authorization'], 'Bearer test-key')
            payload = json.loads(request.content)
            self.assertEqual(payload['model'], 'ecnu-plus')
            self.assertEqual(payload['messages'][0]['content'], '接口测试')
            return httpx.Response(200, json={'choices': [{'message': {'content': ' connected '}}]})
        with self.mock_client(handler):
            self.assertEqual(await self.provider.generate(self.messages), 'connected')

    async def test_max_strength_parameters_and_sampling_defaults(self):
        self.provider.model_name = 'ecnu-max'
        for level in ['off', 'low', 'high', 'max']:
            async def handler(request):
                payload = json.loads(request.content)
                self.assertEqual(payload['model'], 'ecnu-max')
                self.assertEqual(payload['thinking']['type'], 'disabled' if level == 'off' else 'enabled')
                if level == 'off':
                    self.assertNotIn('reasoning_effort', payload)
                    self.assertEqual(payload['temperature'], 0.2)
                else:
                    self.assertEqual(payload['reasoning_effort'], level)
                    self.assertNotIn('temperature', payload)
                    self.assertNotIn('top_p', payload)
                    self.assertGreaterEqual(payload['max_tokens'], app.settings.thinking_max_tokens)
                return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})
            with self.mock_client(handler):
                self.assertEqual(await self.provider.generate(self.messages, thinking_level=level), 'ok')

    async def test_all_endpoints_forward_selected_strength(self):
        self.provider.model_name = 'ecnu-max'
        calls = []
        async def handler(request):
            payload = json.loads(request.content)
            calls.append(payload)
            content = '西医诊断：未明确\n主证：未明确\n兼证：未明确\n方药：未明确\n理由：接口测试'
            if payload.get('stream'):
                return httpx.Response(200, text='data: '+json.dumps({'choices':[{'delta':{'content':content}}]})+'\n\ndata: [DONE]\n\n')
            return httpx.Response(200, json={'choices':[{'message':{'content':content}}]})
        with ExitStack() as stack:
            for service in [app.diagnosis_service, app.dialogue_service, app.workspace_dialogue_service, app.form_autofill_service]:
                stack.enter_context(patch.object(service, '_provider', self.provider))
            stack.enter_context(self.mock_client(handler))
            async with REAL_CLIENT(transport=httpx.ASGITransport(app=app.app), base_url='http://test') as client:
                for route in ['/api/chat', '/api/chat/stream', '/api/dialogue/chat/stream', '/api/workspace/chat/stream']:
                    response = await client.post(route, json={'message':'软件接口测试','use_server_history':False,'thinking_level':'max'})
                    self.assertEqual(response.status_code, 200)
                    if route.endswith('/stream'):
                        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                        self.assertEqual(events[-1]['thinking_level'], 'max')
                    else:
                        self.assertEqual(response.json()['thinking_level'], 'max')
                response = await client.post('/api/form/autofill', json={'source_text':'软件导入测试，无真实患者信息。','thinking_level':'max'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['thinking_level'], 'max')
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(p['reasoning_effort']=='max' for p in calls))

    async def test_invalid_strength_rejected_before_call(self):
        async with REAL_CLIENT(transport=httpx.ASGITransport(app=app.app), base_url='http://test') as client:
            response = await client.post('/api/chat', json={'message':'软件测试','thinking_level':'invalid'})
            self.assertEqual(response.status_code, 422)

    async def test_autofill_stream_emits_complete_fields_before_done(self):
        self.provider.model_name = 'ecnu-max'
        calls = []
        async def handler(request):
            payload = json.loads(request.content)
            calls.append(payload)
            pieces = ['{"patientGender":"男",', '"patientAge":2', '4,"chiefComplaint":"软件\\n', '识别测试",', '"visitType":"初诊"}']
            wire = ''.join('data: '+json.dumps({'choices':[{'delta':{'content':p}}]})+'\n\n' for p in pieces)
            return httpx.Response(200, text=wire+'data: [DONE]\n\n')
        with patch.object(app.form_autofill_service, '_provider', self.provider), self.mock_client(handler):
            async with REAL_CLIENT(transport=httpx.ASGITransport(app=app.app), base_url='http://test') as client:
                response = await client.post('/api/form/autofill/stream', json={'source_text':'软件测试，不含患者资料','thinking_level':'high'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/event-stream', response.headers['content-type'])
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        fields = [e for e in events if e['type']=='field']
        self.assertEqual([e['value'] for e in fields if e['field']=='patientAge'], ['24'])
        self.assertEqual([e['value'] for e in fields if e['field']=='chiefComplaint'], ['软件\n识别测试'])
        self.assertEqual(events[-1]['type'], 'done')
        self.assertEqual(events[-1]['data']['patientGender'], '男')
        self.assertEqual(events[-1]['thinking_level'], 'high')
        self.assertTrue(calls[0]['stream'])
        self.assertEqual(calls[0]['reasoning_effort'], 'high')

    async def test_autofill_stream_interruption_preserves_fields_without_done(self):
        async def broken(messages, *, thinking_level='off'):
            yield '{"chiefComplaint":"软件测试",'
            raise httpx.ReadError('synthetic interruption')
        with patch.object(app.form_autofill_service._provider, 'generate_stream', broken):
            events = [event async for event in app.form_autofill_service.autofill_stream(app.FormAutofillRequest(source_text='软件识别测试，不包含患者信息'))]
        self.assertTrue(any(e['type']=='field' for e in events))
        self.assertEqual(events[-1]['type'], 'error')
        self.assertFalse(any(e['type']=='done' for e in events))

    def test_partial_json_ignores_truncated_numbers_strings_and_nested_keys(self):
        self.assertEqual(app._extract_complete_json_fields('{"patientAge":2'), {})
        self.assertEqual(app._extract_complete_json_fields('{"chiefComplaint":"unfinished'), {})
        fields = app._extract_complete_json_fields('{"unknown":{"patientAge":99},"patientAge":24,')
        self.assertEqual(fields, {'patientAge':24})

    async def test_reasoning_chunks_do_not_enter_final_answer(self):
        async def handler(request):
            return httpx.Response(200, text=(
                'data: {"choices":[{"delta":{"reasoning_content":"synthetic reasoning"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
                'data: [DONE]\n\n'
            ))
        with self.mock_client(handler):
            parts = [part async for part in self.provider.generate_stream(self.messages, thinking_level='high')]
        self.assertEqual(parts, ['answer'])

    async def test_stream_and_regular_share_limit(self):
        active = peak = 0
        async def handler(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.01)
                if json.loads(request.content).get('stream'):
                    return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')
                return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})
            finally:
                active -= 1
        async def stream():
            return ''.join([part async for part in self.provider.generate_stream(self.messages)])
        with self.mock_client(handler):
            results = await asyncio.gather(*(stream() if i % 2 else self.provider.generate(self.messages) for i in range(8)))
        self.assertEqual(results, ['ok'] * 8)
        self.assertEqual(peak, 3)

    async def test_quota_error_does_not_retry(self):
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(429, json={'error': {'message': 'quota'}})
        with self.mock_client(handler):
            with self.assertRaises(httpx.HTTPStatusError):
                _ = [part async for part in self.provider.generate_stream(self.messages)]
        self.assertEqual(calls, 1)

    async def test_stream_ignores_empty_choice_metadata(self):
        async def handler(request):
            return httpx.Response(200, text=(
                'data: {"choices":[],"usage":{"total_tokens":12}}\n\n'
                'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                'data: {"choices":[]}\n\n'
                'data: [DONE]\n\n'
            ))
        with self.mock_client(handler):
            parts = [part async for part in self.provider.generate_stream(self.messages)]
        self.assertEqual(parts, ['ok'])

    async def test_interrupted_stream_does_not_append_second_reply(self):
        calls = 0
        class BrokenStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
                raise httpx.ReadError('synthetic disconnect')
        async def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, stream=BrokenStream())
        parts = []
        with self.mock_client(handler):
            with self.assertRaises(httpx.ReadError):
                async for part in self.provider.generate_stream(self.messages):
                    parts.append(part)
        self.assertEqual(parts, ['first'])
        self.assertEqual(calls, 1)


if __name__ == '__main__':
    unittest.main()
