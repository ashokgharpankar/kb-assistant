import type { Source } from '../lib/types'

interface Props {
  sources: Source[]
  /** Numbers the answer cited; null while the answer is still being written. */
  cited: ReadonlySet<number> | null
  active: number | null
}

export function SourceList({ sources, cited, active }: Props) {
  if (sources.length === 0) return null
  return (
    <section className="sources" aria-label="Sources">
      <h2>Sources</h2>
      <ol>
        {sources.map((source) => {
          const isCited = cited?.has(source.number) ?? false
          const classes = ['source']
          if (active === source.number) classes.push('active')
          if (cited && !isCited) classes.push('uncited')
          return (
            <li key={source.number} id={`source-${source.number}`} className={classes.join(' ')}>
              <div className="source-head">
                <span className="source-number">{source.number}</span>
                <span className="source-title">
                  {source.section} · p.{source.page}
                </span>
                {cited && <span className="badge">{isCited ? 'cited' : 'not cited'}</span>}
              </div>
              <div className="similarity" title="Similarity to your question">
                <span style={{ width: `${Math.round(source.similarity * 100)}%` }} />
                <small>{source.similarity.toFixed(2)}</small>
              </div>
              <p className="excerpt">{source.excerpt}</p>
              <small className="document">{source.document_title}</small>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
