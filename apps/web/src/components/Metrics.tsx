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
        <dd>{cost === 0 ? '$0 (local)' : `$${cost.toFixed(6)}`}</dd>
      </div>
    </dl>
  )
}
