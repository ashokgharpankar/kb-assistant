// Shapes of what the API sends. They mirror apps/api/src/kb_api/main.py.

/** One retrieved chunk, sent before the answer starts. */
export interface Source {
  number: number
  document_title: string
  section: string
  page: number
  similarity: number
  excerpt: string
}

/** A source the answer actually cited. */
export interface Citation {
  number: number
  document_title: string
  section: string
  page: number
  similarity: number
}

/** The final event: the full answer plus usage, cost and timings. */
export interface AskResult {
  answer: string
  citations: Citation[]
  answered_from_context: boolean
  model: string
  input_tokens: number
  output_tokens: number
  cost_usd: string
  time_to_first_token_ms: number | null
  total_ms: number
}

export type StreamEvent =
  | { type: 'sources'; sources: Source[] }
  | { type: 'token'; text: string }
  | { type: 'done'; result: AskResult }
  | { type: 'error'; detail: string }

export interface Health {
  status: string
  version: string
  env: string
  llm_provider: string
}
