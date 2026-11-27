import { useEffect, useMemo, useState } from 'react'
import { AnswerText } from './components/AnswerText'
import { AskForm } from './components/AskForm'
import { Metrics } from './components/Metrics'
import { SourceList } from './components/SourceList'
import { isBusy, useAsk } from './hooks/useAsk'
import { getHealth } from './lib/api'
import type { Session } from './lib/auth'
import type { Health } from './lib/types'

const STATUS_TEXT: Partial<Record<string, string>> = {
  retrieving: 'Searching the knowledge base…',
  generating: 'Writing the answer…',
  stopped: 'Stopped.',
}

interface Props {
  /** The signed-in user, or null when this UI runs without sign-in (demo, tests). */
  session: Session | null
}

export default function App({ session }: Props) {
  const { state, ask, stop } = useAsk(session?.getAccessToken)
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
  const overBudget = state.status === 'done' && state.result?.degraded === 'over_budget'
  const notFound =
    !overBudget && state.status === 'done' && state.result && !state.result.answered_from_context
  // Phase 7b: say so when the answer isn't fully backed by its sources, instead of hiding it.
  const weakGrounding =
    !notFound &&
    state.result &&
    ((state.result.grounding_score ?? 1) < 0.5 || (state.result.unknown_terms?.length ?? 0) > 0)

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
        {session && (
          <span className="user">
            <span title="Signed in">{session.email}</span>
            <button type="button" className="link" onClick={session.signOut}>
              Sign out
            </button>
          </span>
        )}
      </header>

      <main>
        <div className="conversation">
          <AskForm busy={busy} onAsk={onAsk} onStop={stop} />

          {state.status !== 'idle' && (
            <article className="answer">
              <h2 className="question">{state.question}</h2>
              <p className="status" role="status">
                {state.status === 'generating' && state.escalatedTo
                  ? 'Checking with a larger model…'
                  : (STATUS_TEXT[state.status] ?? '')}
              </p>
              {state.status === 'error' && (
                <div className="error" role="alert">
                  {state.errorStatus === 401 ? (
                    session ? (
                      <>
                        Your session has expired.{' '}
                        <button type="button" className="link" onClick={session.signIn}>
                          Sign in again
                        </button>
                      </>
                    ) : (
                      <>
                        The API requires sign-in, but this page has no Cognito settings. Add them to{' '}
                        <code>apps/web/.env.local</code> (see <code>make cognito-env</code>) and
                        restart <code>make web-dev</code>.
                      </>
                    )
                  ) : (
                    state.error
                  )}
                </div>
              )}
              {overBudget ? (
                <p className="not-found" role="note">
                  {state.result?.answer}
                </p>
              ) : notFound ? (
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
              {weakGrounding && state.result && (
                <p className="grounding-warning" role="note">
                  Parts of this answer aren&apos;t clearly supported by the cited sources
                  {state.result.unknown_terms?.length
                    ? ` (not in any source: ${state.result.unknown_terms.join(', ')})`
                    : ''}
                  . Check the sources before relying on it.
                </p>
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
