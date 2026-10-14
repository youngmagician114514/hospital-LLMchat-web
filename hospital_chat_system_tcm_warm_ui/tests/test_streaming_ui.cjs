const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { ReadableStream } = require('node:stream/web');
const scope = { window: {}, TextDecoder, setTimeout, clearTimeout };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/streaming.js'), 'utf8'), scope);
const { createWriter, readEvents } = scope.window.StreamUI;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const paints = [];
  const writer = createWriter(text => paints.push(text));
  const reply = '这是合并到同一网络片段中的完整回复。🩺'.repeat(4);
  writer.push(reply);
  await pause(45);
  assert(paints.length > 0 && paints.at(-1).length < reply.length, 'burst must remain visibly incomplete after its first paint');
  await writer.finish();
  assert.equal(paints.at(-1), reply);
  assert(paints.length > 3 && paints.every(text => reply.startsWith(text)), 'paints must append monotonically without splitting emoji');
  writer.push('追加');
  await writer.finish();
  assert.equal(paints.at(-1), reply + '追加');

  let stoppedPaints = 0;
  const stopped = createWriter(() => stoppedPaints++);
  stopped.push('连接中断后不应继续绘制');
  const drain = stopped.finish();
  stopped.stop();
  await drain;
  await pause(35);
  assert.equal(stoppedPaints, 0);
  assert.equal(stopped.getText(), '连接中断后不应继续绘制');

  const wire = 'data: {"type":"token","delta":"中文🩺"}\r\n\r\ndata: {"type":"done"}';
  const bytes = new TextEncoder().encode(wire);
  const response = { body: new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i += 2) controller.enqueue(bytes.slice(i, i + 2));
    controller.close();
  } }) };
  const events = [];
  for await (const event of readEvents(response)) events.push(event);
  assert.equal(events[0].delta, '中文🩺');
  assert.equal(events[1].type, 'done', 'EOF event without trailing blank line must survive');
  assert.equal(response.body.locked, false);
  console.log('PASS: burst rendering, monotonic Unicode, resumed rendering, interrupted rendering, fragmented CRLF SSE and EOF');
})().catch(error => { console.error(error); process.exitCode = 1; });
