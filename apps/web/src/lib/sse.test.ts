import { describe, expect, it } from 'vitest'
import { readSSE, SSEParser, type SSEMessage } from './sse'
import { streamBody } from '../test/fakeServer'

const STREAM =
  'event: sources\ndata: [1,2]\n\n' +
  ': keep-alive comment\n\n' +
  'event: token\ndata: {"text":"a\\nb"}\n\n' +
  'data: line one\ndata: line two\n\n' +
  'event: done\ndata: {}\n\n'

const EXPECTED: SSEMessage[] = [
  { event: 'sources', data: '[1,2]' },
  { event: 'token', data: '{"text":"a\\nb"}' },
  { event: 'message', data: 'line one\nline two' },
  { event: 'done', data: '{}' },
]

describe('SSEParser', () => {
  it('parses events, skips comments and joins multi-line data', () => {
    expect(new SSEParser().push(STREAM)).toEqual(EXPECTED)
  })

  it('gives the same result wherever the network splits the stream', () => {
    for (let cut = 1; cut < STREAM.length; cut++) {
      const parser = new SSEParser()
      const messages = [...parser.push(STREAM.slice(0, cut)), ...parser.push(STREAM.slice(cut))]
      expect(messages, `split at ${cut}`).toEqual(EXPECTED)
    }
  })

  it('handles \\r\\n line endings, even when split between \\r and \\n', () => {
    const crlf = STREAM.replaceAll('\n', '\r\n')
    for (let cut = 1; cut < crlf.length; cut++) {
      const parser = new SSEParser()
      expect([...parser.push(crlf.slice(0, cut)), ...parser.push(crlf.slice(cut))]).toEqual(
        EXPECTED,
      )
    }
  })

  it('ignores an event with no data and an unfinished event', () => {
    const parser = new SSEParser()
    expect(parser.push('event: ping\n\nevent: token\ndata: {"te')).toEqual([])
  })
})

describe('readSSE', () => {
  it('keeps a multi-byte character that is split across network chunks', async () => {
    const bytes = new TextEncoder().encode('data: shuﬄe ✓\n\n')
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        // the ﬄ ligature is 3 bytes; split in the middle of it
        controller.enqueue(bytes.slice(0, 11))
        controller.enqueue(bytes.slice(11))
        controller.close()
      },
    })
    const messages: SSEMessage[] = []
    for await (const m of readSSE(body)) messages.push(m)
    expect(messages).toEqual([{ event: 'message', data: 'shuﬄe ✓' }])
  })

  it('reads every message from a chunked body', async () => {
    const messages: SSEMessage[] = []
    for await (const m of readSSE(streamBody([STREAM.slice(0, 20), STREAM.slice(20)])))
      messages.push(m)
    expect(messages).toEqual(EXPECTED)
  })
})
