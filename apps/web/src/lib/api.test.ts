import { describe, expect, it, vi } from 'vitest'
import { ApiError, askStream, getHealth } from './api'
import type { StreamEvent } from './types'
import { answerChunks, jsonResponse, RESULT, sse, sseResponse, SOURCES } from '../test/fakeServer'

async function collect(stream: AsyncGenerator<StreamEvent>): Promise<StreamEvent[]> {
  const events: StreamEvent[] = []
  for await (const event of stream) events.push(event)
  return events
}

describe('askStream', () => {
  it('posts the question and yields sources, tokens, then done', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(sseResponse(answerChunks()))
    const events = await collect(askStream('How should I design for failure?'))

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/ask/stream',
      expect.objectContaining({
        method: 'POST',
        body: '{"question":"How should I design for failure?"}',
      }),
    )
    expect(events.map((e) => e.type)).toEqual(['sources', 'token', 'token', 'done'])
    expect(events[0]).toEqual({ type: 'sources', sources: SOURCES })
    expect(events[3]).toEqual({ type: 'done', result: RESULT })
  })

  it('sends the access token as a Bearer header, and no header without one', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(sseResponse(answerChunks())))
    await collect(askStream('How?', undefined, 'token-1'))
    await collect(askStream('How?'))

    const headers = fetchMock.mock.calls.map(([, init]) => init?.headers as Record<string, string>)
    expect(headers[0]?.Authorization).toBe('Bearer token-1')
    expect(headers[1]).not.toHaveProperty('Authorization')
  })

  it('yields an error event sent mid-stream', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      sseResponse([
        sse('sources', []),
        sse('error', { detail: 'answering is temporarily unavailable' }),
      ]),
    )
    const events = await collect(askStream('How?'))
    expect(events.at(-1)).toEqual({ type: 'error', detail: 'answering is temporarily unavailable' })
  })

  it('skips unknown events', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      sseResponse([sse('progress', { pct: 50 }), sse('done', RESULT)]),
    )
    expect((await collect(askStream('How?'))).map((e) => e.type)).toEqual(['done'])
  })

  it('reports FastAPI validation errors in plain words', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ detail: [{ msg: 'String should have at least 3 characters' }] }, 422),
    )
    await expect(collect(askStream('x'))).rejects.toEqual(
      new ApiError('String should have at least 3 characters', 422),
    )
  })

  it('fails if the stream ends before done', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(sseResponse([sse('sources', [])]))
    await expect(collect(askStream('How?'))).rejects.toThrow('ended unexpectedly')
  })
})

describe('getHealth', () => {
  it('returns the health payload', async () => {
    const health = { status: 'ok', version: '0.2.0', env: 'dev', llm_provider: 'ollama' }
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(health))
    await expect(getHealth()).resolves.toEqual(health)
  })

  it('uses the status text when the error body is not JSON', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('Bad gateway', { status: 502, statusText: 'Bad Gateway' }),
    )
    await expect(getHealth()).rejects.toThrow('Request failed (502 Bad Gateway)')
  })
})
