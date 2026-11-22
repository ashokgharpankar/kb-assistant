import { useEffect, useMemo, useState } from 'react'
import { AnswerText } from './components/AnswerText'
import { AskForm } from './components/AskForm'
import { Metrics } from './components/Metrics'
import { SourceList } from './components/SourceList'
import { isBusy, useAsk } from './hooks/useAsk'
import { getHealth } from './lib/api'
import type { Health } from './lib/types'

const STATUS_TEXT: Partial<Record<string, string>> = {
  retrieving: 'Searching the knowledge base…',
  generating: 'Writing the answer…',
  stopped: 'Stopped.',
}

export default function App() {
  const { state, ask, stop } = useAsk()
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [active, setActive] = useState<number | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal)
      .then(setHealth)
      .catch(() => {
        if (!controller.signal.aborted) setHealthError(true)
      })
    return () => controller.abort()
  }, [])

  const busy = isBusy(state.status)
  const sourceNumbers = useMemo(() => new Set(state.sources.map((s) => s.number)), [state.sources])
  const cited = useMemo(
    () => (state.result ? new Set(state.result.citations.map((c) => c.number)) : null),
    [state.result],
  )
  const notFound = state.status === 'done' && state.result && !state.result.answered_from_context

  const showSource = (number: number) => {
    setActive(number)
    document
      .getElementById(`source-${number}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  const onAsk = (question: string) => {
    setActive(null)
    void ask(question)
  }

  return (
    <div className="app">
      <header>
        <h1>KB Assistant</h1>
        {health && (
          <span className="pill" title={`API ${health.version}, ${health.env}`}>
            {health.llm_provider}
          </span>
        )}
        {healthError && <span className="pill pill-error">API unreachable</span>}
      </header>

      <main>
        <div className="conversation">
          <AskForm busy={busy} onAsk={onAsk} onStop={stop} />

          {state.status !== 'idle' && (
            <article className="answer">
              <h2 className="question">{state.question}</h2>
              <p className="status" role="status">
                {STATUS_TEXT[state.status] ?? ''}
              </p>
              {state.status === 'error' && (
                <p className="error" role="alert">
                  {state.error}
                </p>
              )}
              {notFound ? (
                <p className="not-found">
                  The knowledge base has nothing close enough to this question, so no answer was
                  generated.
                </p>
              ) : (
                state.text && (
                  <AnswerText
                    text={state.text}
                    sourceNumbers={sourceNumbers}
                    streaming={state.status === 'generating'}
                    onCite={showSource}
                  />
                )
              )}
              {state.result && <Metrics result={state.result} />}
            </article>
          )}
        </div>

        <SourceList sources={state.sources} cited={cited} active={active} />
      </main>
    </div>
  )
}
