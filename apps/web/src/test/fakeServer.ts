// Builds fetch Responses that look like the real API, for tests.
import type { AskResult, Source } from '../lib/types'

export const SOURCES: Source[] = [
  {
    number: 1,
    document_title: 'AWS Well-Architected Framework',
    section: 'Framework > Reliability',
    page: 765,
    similarity: 0.746,
    excerpt: 'Design your workload to withstand component failures…',
  },
  {
    number: 2,
    document_title: 'AWS Well-Architected Framework',
    section: 'Framework > Reliability',
    page: 770,
    similarity: 0.745,
    excerpt: 'A dampening period prevents the workload from failing back…',
  },
]

export const RESULT: AskResult = {
  answer: '* Expect **component failures** [1].\n* Use static stability [7].',
  citations: [
    {
      number: 1,
      document_title: 'AWS Well-Architected Framework',
      section: 'Framework > Reliability',
      page: 765,
      similarity: 0.746,
    },
  ],
  answered_from_context: true,
  model: 'llama3.2',
  input_tokens: 1055,
  output_tokens: 220,
  cost_usd: '0',
  time_to_first_token_ms: 1200,
  total_ms: 4400,
}

export const sse = (event: string, data: unknown) =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

/**
 * A streaming body that releases its chunks one by one, optionally waiting on a
 * gate before the second chunk. Like real fetch, aborting the signal fails the read.
 */
export function streamBody(
  chunks: string[],
  gate?: Promise<void>,
  signal?: AbortSignal,
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  let i = 0
  return new ReadableStream<Uint8Array>({
    start(controller) {
      signal?.addEventListener('abort', () =>
        controller.error(new DOMException('The operation was aborted.', 'AbortError')),
      )
    },
    async pull(controller) {
      if (i === 1 && gate) await gate
      const chunk = chunks[i++]
      if (chunk === undefined) controller.close()
      else controller.enqueue(encoder.encode(chunk))
    },
  })
}

export function sseResponse(
  chunks: string[],
  gate?: Promise<void>,
  signal?: AbortSignal,
): Response {
  return new Response(streamBody(chunks, gate, signal), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

export const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

export const answerChunks = (result: AskResult = RESULT, sources: Source[] = SOURCES) => [
  sse('sources', sources),
  sse('token', { text: '* Expect **component ' }),
  sse('token', { text: 'failures** [1].\n* Use static stability [7].' }),
  sse('done', result),
]
