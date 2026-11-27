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
  /** Phase 7b grounding check; absent from older APIs, so optional. */
  grounding_score?: number | null
  unsupported?: string[]
  unknown_terms?: string[]
  /** Phase 8a answer cache: "exact" or "semantic" when no model call was made. */
  cache?: 'exact' | 'semantic' | null
  cache_similarity?: number | null
  cost_saved_usd?: string
  /** Phase 8b: the model that tried first when routing escalated; spend-cap level. */
  escalated_from?: string | null
  degraded?: 'economy' | 'over_budget' | null
}

/** Phase 8b routing: a larger model answers next; with reset, drop the text so far. */
export interface Escalation {
  from_model: string
  to_model: string
  reset: boolean
}

export type StreamEvent =
  | { type: 'sources'; sources: Source[] }
  | { type: 'token'; text: string }
  | { type: 'escalate'; escalation: Escalation }
  | { type: 'done'; result: AskResult }
  | { type: 'error'; detail: string }

export interface Health {
  status: string
  version: string
  env: string
  llm_provider: string
}
