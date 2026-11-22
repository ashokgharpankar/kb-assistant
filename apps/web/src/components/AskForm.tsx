import { useState, type FormEvent, type KeyboardEvent } from 'react'

const MIN_LENGTH = 3 // the API rejects shorter questions
const MAX_LENGTH = 1000

interface Props {
  busy: boolean
  onAsk: (question: string) => void
  onStop: () => void
}

export function AskForm({ busy, onAsk, onStop }: Props) {
  const [question, setQuestion] = useState('')
  const trimmed = question.trim()
  const canAsk = !busy && trimmed.length >= MIN_LENGTH

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    if (canAsk) onAsk(trimmed)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter asks; Shift+Enter adds a new line.
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form className="ask-form" onSubmit={submit}>
      <label htmlFor="question" className="visually-hidden">
        Your question
      </label>
      <textarea
        id="question"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask about the AWS Well-Architected Framework…"
        maxLength={MAX_LENGTH}
        rows={2}
      />
      {busy ? (
        <button type="button" className="secondary" onClick={onStop}>
          Stop
        </button>
      ) : (
        <button type="submit" disabled={!canAsk}>
          Ask
        </button>
      )}
    </form>
  )
}
