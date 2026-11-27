import { readSSE } from './sse'
import type { AskResult, Escalation, Health, Source, StreamEvent } from './types'

/** Same-origin path; Vite (dev) and CloudFront (AWS) forward it to the API. */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? '/api'

export class ApiError extends Error {
  readonly status: number | undefined

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** FastAPI errors look like {"detail": "..."} or {"detail": [{"msg": "..."}]}. */
async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'detail' in body) {
      const { detail } = body as { detail: unknown }
      if (typeof detail === 'string') return detail
      if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0] as { msg?: unknown }
        if (typeof first.msg === 'string') return first.msg
      }
    }
  } catch {
    // not JSON: fall through to the status text
  }
  return `Request failed (${response.status} ${response.statusText})`.trim()
}

/**
 * Asks a question and yields events as they arrive: sources, then tokens, then
 * done (or error). Pass an AbortSignal to stop; the server stops generating too.
 */
export async function* askStream(
  question: string,
  signal?: AbortSignal,
  accessToken?: string,
): AsyncGenerator<StreamEvent> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  // This header is why we use fetch and not EventSource, which can't send headers.
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`

  const response = await fetch(`${API_BASE}/ask/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ question }),
    signal,
  })
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status)
  if (!response.body) throw new ApiError('The server sent an empty response')

  for await (const message of readSSE(response.body)) {
    const data: unknown = JSON.parse(message.data)
    switch (message.event) {
      case 'sources':
        yield { type: 'sources', sources: data as Source[] }
        break
      case 'token':
        yield { type: 'token', text: (data as { text: string }).text }
        break
      case 'escalate':
        yield { type: 'escalate', escalation: data as Escalation }
        break
      case 'done':
        yield { type: 'done', result: data as AskResult }
        return
      case 'error':
        yield { type: 'error', detail: (data as { detail: string }).detail }
        return
      default:
        // Unknown events are skipped, so the server can add new ones safely.
        break
    }
  }
  throw new ApiError('The answer stream ended unexpectedly')
}

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch(`${API_BASE}/health`, { signal })
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status)
  return (await response.json()) as Health
}
