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

    async def test_complete_example_is_sent_only_to_diagnosis_routes(self):
        example = json.loads((Path(app.__file__).parent / 'prompts' / 'diagnosis_example.json').read_text(encoding='utf-8'))
        prompts = []
        async def handler(request):
            payload = json.loads(request.content)
            prompts.append(payload['messages'][0]['content'])
            content = '软件接口测试'
            if payload.get('stream'):
                return httpx.Response(200, text='data: '+json.dumps({'choices':[{'delta':{'content':content}}]})+'\n\ndata: [DONE]\n\n')
            return httpx.Response(200, json={'choices':[{'message':{'content':content}}]})
        with ExitStack() as stack:
            for service in [app.diagnosis_service, app.dialogue_service, app.workspace_dialogue_service, app.form_autofill_service]:
                stack.enter_context(patch.object(service, '_provider', self.provider))
            stack.enter_context(self.mock_client(handler))
            async with REAL_CLIENT(transport=httpx.ASGITransport(app=app.app), base_url='http://test') as client:
                for route in ['/api/chat','/api/chat/stream','/api/dialogue/chat/stream','/api/workspace/chat/stream']:
                    response = await client.post(route, json={'message':'软件接口测试','thinking_level':'off','use_server_history':False})
                    self.assertEqual(response.status_code, 200)
                response = await client.post('/api/form/autofill/stream', json={'source_text':'软件识别测试，不含患者资料','thinking_level':'off'})
                self.assertEqual(response.status_code, 200)
        for prompt in prompts[:2]:
            self.assertIn(example['introduction'], prompt)
            self.assertIn(example['output'], prompt)
            self.assertIn('理由根据本次病历填写', prompt)
        for prompt in prompts[2:]:
            self.assertNotIn(example['output'], prompt)

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

    async def test_reasoning_chunks_are_separate_from_content(self):
        async def handler(request):
            return httpx.Response(200, text=(
                'data: {"choices":[{"delta":{"reasoning_content":"synthetic reasoning"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
                'data: [DONE]\n\n'
            ))
        with self.mock_client(handler):
            parts = [part async for part in self.provider.generate_stream(self.messages, thinking_level='high')]
        self.assertEqual(parts, [app.ReasoningDelta('synthetic reasoning'), 'answer'])

    async def test_all_stream_routes_separate_reasoning_from_results_and_history(self):
        reasoning = 'synthetic reasoning: {"patientAge":99}'
        async def handler(request):
            payload = json.loads(request.content)
            content = '{"chiefComplaint":"软件测试"}' if payload['messages'][0]['content'] == app.FORM_IMPORT_SYSTEM_PROMPT else '软件测试正文'
            wire = ''.join('data: '+json.dumps({'choices':[{'delta':delta}]})+'\n\n' for delta in [
                {'reasoning_content': reasoning[:10]}, {'reasoning_content': reasoning[10:]}, {'content':content}])
            return httpx.Response(200, text=wire+'data: [DONE]\n\n')
        with ExitStack() as stack:
            for service in [app.diagnosis_service, app.dialogue_service, app.workspace_dialogue_service, app.form_autofill_service]:
                stack.enter_context(patch.object(service, '_provider', self.provider))
            stack.enter_context(self.mock_client(handler))
            async with REAL_CLIENT(transport=httpx.ASGITransport(app=app.app), base_url='http://test') as client:
                for route in ['/api/chat/stream', '/api/dialogue/chat/stream', '/api/workspace/chat/stream', '/api/form/autofill/stream']:
                    body = {'source_text':'软件识别测试，不包含患者资料'} if '/autofill/' in route else {'message':'软件测试'}
                    response = await client.post(route, json={**body,'thinking_level':'high'})
                    self.assertEqual(response.status_code, 200)
                    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                    self.assertEqual(''.join(e['delta'] for e in events if e['type']=='reasoning'), reasoning)
                    self.assertEqual(events[-1]['type'], 'done')
                    self.assertNotIn('synthetic reasoning', json.dumps(events[-1]))
                    self.assertFalse(any('synthetic reasoning' in e.get('delta','') for e in events if e['type']=='token'))
                    if '/autofill/' in route:
                        self.assertEqual(events[-1]['data']['patientAge'], '')
                        self.assertEqual(events[-1]['data']['chiefComplaint'], '软件测试')

    async def test_reasoning_interruption_does_not_retry_or_complete(self):
        calls = 0
        class BrokenStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"choices":[{"delta":{"reasoning_content":"partial reasoning"}}]}\n\n'
                raise httpx.ReadError('synthetic disconnect')
        async def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, stream=BrokenStream())
        with patch.object(app.dialogue_service, '_provider', self.provider), self.mock_client(handler):
            events = [e async for e in app.dialogue_service.chat_stream(app.ChatRequest(message='软件测试'))]
        self.assertEqual(events[0], {'type':'reasoning','delta':'partial reasoning'})
        self.assertEqual(events[-1]['type'], 'error')
        self.assertFalse(any(e['type']=='done' for e in events))
        self.assertEqual(calls, 1)

    async def test_reasoning_without_answer_does_not_start_second_request(self):
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, text='data: {"choices":[{"delta":{"reasoning_content":"only reasoning"}}]}\n\ndata: [DONE]\n\n')
        with patch.object(app.dialogue_service, '_provider', self.provider), self.mock_client(handler):
            events = [e async for e in app.dialogue_service.chat_stream(app.ChatRequest(message='软件测试'))]
        self.assertEqual(events[-1]['type'], 'error')
        self.assertEqual(calls, 1)

    async def test_stream_fallback_keeps_reasoning_separate(self):
        async def handler(request):
            if json.loads(request.content).get('stream'):
                raise httpx.ReadError('synthetic stream unavailable')
            return httpx.Response(200, json={'choices':[{'message':{'reasoning_content':'fallback reasoning','content':'answer'}}]})
        with self.mock_client(handler):
            parts = [part async for part in self.provider.generate_stream(self.messages)]
        self.assertEqual(parts, [app.ReasoningDelta('fallback reasoning'), 'answer'])

    async def test_vllm_plain_stream_stays_compatible(self):
        self.provider._base_url = 'http://127.0.0.1:8001/v1'
        self.provider.model_name = 'local-model'
        async def handler(request):
            payload = json.loads(request.content)
            self.assertNotIn('thinking', payload)
            self.assertNotIn('reasoning_effort', payload)
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"local answer"}}]}\n\ndata: [DONE]\n\n')
        with self.mock_client(handler):
            parts = [part async for part in self.provider.generate_stream(self.messages, thinking_level='high')]
        self.assertEqual(parts, ['local answer'])

    def test_vllm_qwen_thinking_template_is_only_enabled_for_qwen3_models(self):
        for model in ['qwen3.5-4b-bf16', 'QuantTrio/Qwen3.5-9B-AWQ', 'qwen3-14b-int4', 'qwen3.8-27b-int4', 'qwen2.5-7b-instruct']:
            with self.subTest(model=model), patch.object(app, 'settings', replace(app.settings, model_provider='vllm_openai', vllm_model=model)):
                provider = app.build_provider()
                for level in ['off', 'low', 'high', 'max']:
                    payload = provider._build_payload(self.messages, stream=True, thinking_level=level)
                    if model == 'qwen2.5-7b-instruct':
                        self.assertNotIn('chat_template_kwargs', payload)
                    else:
                        self.assertEqual(payload['chat_template_kwargs'], {'enable_thinking': level != 'off'})
                        if level != 'off':
                            self.assertGreaterEqual(payload['max_tokens'], app.settings.thinking_max_tokens)
                    if model.startswith('qwen3.8') and level != 'off':
                        self.assertEqual(payload['reasoning_effort'], {'low':'low','high':'medium','max':'xhigh'}[level])
                    else:
                        self.assertNotIn('reasoning_effort', payload)
                    self.assertNotIn('thinking', payload)

    async def test_modern_vllm_reasoning_field_stays_separate_and_is_not_duplicated(self):
        async def handler(request):
            return httpx.Response(200, text=(
                'data: {"choices":[{"delta":{"reasoning":"modern reasoning"}}]}\n\n'
                'data: {"choices":[{"delta":{"reasoning_content":"shared","reasoning":"shared"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
                'data: [DONE]\n\n'
            ))
        with self.mock_client(handler):
            parts = [part async for part in self.provider.generate_stream(self.messages)]
        self.assertEqual(parts, [app.ReasoningDelta('modern reasoning'), app.ReasoningDelta('shared'), 'answer'])

    async def test_modern_vllm_reasoning_is_kept_in_stream_fallback(self):
        async def handler(request):
            if json.loads(request.content).get('stream'):
                raise httpx.ReadError('synthetic stream unavailable')
            return httpx.Response(200, json={'choices':[{'message':{'reasoning':'modern fallback reasoning','content':'answer'}}]})
        with self.mock_client(handler):
            parts = [part async for part in self.provider.generate_stream(self.messages)]
        self.assertEqual(parts, [app.ReasoningDelta('modern fallback reasoning'), 'answer'])

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
