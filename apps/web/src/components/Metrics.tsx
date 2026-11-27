import type { AskResult } from '../lib/types'

const seconds = (ms: number) => `${(ms / 1000).toFixed(1)} s`

export function Metrics({ result }: { result: AskResult }) {
  const cost = Number(result.cost_usd)
  return (
    <dl className="metrics">
      <div>
        <dt>Model</dt>
        <dd>{result.model}</dd>
      </div>
      {result.time_to_first_token_ms !== null && (
        <div>
          <dt>First word</dt>
          <dd>{seconds(result.time_to_first_token_ms)}</dd>
        </div>
      )}
      <div>
        <dt>Total</dt>
        <dd>{seconds(result.total_ms)}</dd>
      </div>
      <div>
        <dt>Tokens</dt>
        <dd>
          {result.input_tokens.toLocaleString()} in / {result.output_tokens.toLocaleString()} out
        </dd>
      </div>
      <div>
        <dt>Cost</dt>
        <dd>{result.cache ? '$0 (cached)' : cost === 0 ? '$0 (local)' : `$${cost.toFixed(6)}`}</dd>
      </div>
      {result.cache && (
        <div>
          <dt>Source</dt>
          <dd className="cache-badge">
            {result.cache === 'exact'
              ? 'From cache (same question)'
              : `From cache (similar question, ${Math.round((result.cache_similarity ?? 0) * 100)}%)`}
          </dd>
        </div>
      )}
    </dl>
  )
}
