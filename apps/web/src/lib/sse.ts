// A small Server-Sent Events reader for fetch() responses.
//
// The browser's built-in EventSource only does GET requests and cannot send
// headers. /ask/stream is a POST with a JSON body, and from Phase 2c it needs an
// Authorization header, so we read the response body ourselves.

export interface SSEMessage {
  event: string
  data: string
}

/**
 * Turns text chunks into complete SSE messages.
 *
 * Network chunks can end anywhere: mid-line, mid-field, even between the \r and
 * \n of a line break. The parser keeps the unfinished part until more arrives.
 */
export class SSEParser {
  private buffer = ''
  private event = ''
  private data: string[] = []

  push(chunk: string): SSEMessage[] {
    let text = this.buffer + chunk
    // A trailing \r may be the first half of \r\n: wait for the next chunk.
    let held = ''
    if (text.endsWith('\r')) {
      held = '\r'
      text = text.slice(0, -1)
    }
    const lines = text.replace(/\r\n?/g, '\n').split('\n')
    this.buffer = (lines.pop() ?? '') + held

    const messages: SSEMessage[] = []
    for (const line of lines) {
      const message = this.line(line)
      if (message) messages.push(message)
    }
    return messages
  }

  private line(line: string): SSEMessage | undefined {
    if (line === '') {
      // A blank line ends a message. A message with no data is ignored (per the spec).
      const message =
        this.data.length > 0
          ? { event: this.event || 'message', data: this.data.join('\n') }
          : undefined
      this.event = ''
      this.data = []
      return message
    }
    if (line.startsWith(':')) return undefined // a comment, often used as a keep-alive

    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') this.event = value
    else if (field === 'data') this.data.push(value)
    // "id" and "retry" are only used for automatic reconnects, which we don't do.
    return undefined
  }
}

/** Reads a response body as a stream of SSE messages. */
export async function* readSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<SSEMessage> {
  const parser = new SSEParser()
  // stream: true keeps a multi-byte character (é, ﬁ, emoji) split across two
  // network chunks intact instead of decoding each half as garbage.
  const decoder = new TextDecoder()
  const reader = body.getReader()
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) {
        yield* parser.push(decoder.decode())
        return
      }
      yield* parser.push(decoder.decode(value, { stream: true }))
    }
  } finally {
    reader.releaseLock()
  }
}
