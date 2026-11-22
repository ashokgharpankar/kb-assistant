import { Fragment, useMemo } from 'react'
import { parseBlocks, type Inline } from '../lib/citations'

interface Props {
  text: string
  /** Numbers of the sources that were actually retrieved. */
  sourceNumbers: ReadonlySet<number>
  streaming: boolean
  onCite: (number: number) => void
}

export function AnswerText({ text, sourceNumbers, streaming, onCite }: Props) {
  const blocks = useMemo(() => parseBlocks(text), [text])

  const renderInlines = (inlines: Inline[]) =>
    inlines.map((part, i) => {
      if (part.kind === 'text') return <Fragment key={i}>{part.text}</Fragment>
      if (part.kind === 'bold') return <strong key={i}>{part.text}</strong>
      if (sourceNumbers.has(part.number)) {
        return (
          <button
            key={i}
            type="button"
            className="cite"
            onClick={() => onCite(part.number)}
            aria-label={`Show source ${part.number}`}
          >
            {part.number}
          </button>
        )
      }
      // The model cited a number that was never retrieved: show it, flagged.
      return (
        <span key={i} className="cite cite-invalid" title="Not one of the retrieved sources">
          {part.number}
        </span>
      )
    })

  // While streaming, a caret follows the last word written.
  const caret = streaming ? <span className="caret" aria-hidden="true" /> : null
  const last = blocks.length - 1

  return (
    <div className="answer-text" aria-busy={streaming}>
      {blocks.map((block, i) => {
        if (block.kind === 'paragraph') {
          return (
            <p key={i}>
              {renderInlines(block.inlines)}
              {i === last && caret}
            </p>
          )
        }
        const items = block.items.map((item, j) => (
          <li key={j}>
            {renderInlines(item)}
            {i === last && j === block.items.length - 1 && caret}
          </li>
        ))
        return block.ordered ? <ol key={i}>{items}</ol> : <ul key={i}>{items}</ul>
      })}
    </div>
  )
}
