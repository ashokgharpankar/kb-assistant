// Splits answer text into plain text, bold text and [n] citation markers, and
// groups lines into paragraphs and lists. Rendering stays in React (no HTML from
// the model is ever inserted), so a model output containing <script> is just text.

export type Inline =
  { kind: 'text'; text: string } | { kind: 'bold'; text: string } | { kind: 'cite'; number: number }

export type Block =
  { kind: 'paragraph'; inlines: Inline[] } | { kind: 'list'; ordered: boolean; items: Inline[][] }

const TOKEN = /\*\*([^*]+)\*\*|\[(\d+)\]/g
const BULLET = /^\s*[-*•]\s+/
const NUMBERED = /^\s*\d+[.)]\s+/

export function parseInlines(text: string): Inline[] {
  const out: Inline[] = []
  let last = 0
  for (const match of text.matchAll(TOKEN)) {
    const index = match.index
    if (index > last) out.push({ kind: 'text', text: text.slice(last, index) })
    if (match[1] !== undefined) out.push({ kind: 'bold', text: match[1] })
    else out.push({ kind: 'cite', number: Number(match[2]) })
    last = index + match[0].length
  }
  if (last < text.length) out.push({ kind: 'text', text: text.slice(last) })
  return out
}

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = []
  let paragraph: string[] = []

  const flush = () => {
    if (paragraph.length > 0) {
      blocks.push({ kind: 'paragraph', inlines: parseInlines(paragraph.join(' ')) })
      paragraph = []
    }
  }

  for (const line of text.split('\n')) {
    const ordered = NUMBERED.test(line)
    if (ordered || BULLET.test(line)) {
      flush()
      const item = parseInlines(line.replace(ordered ? NUMBERED : BULLET, ''))
      const previous = blocks.at(-1)
      if (previous?.kind === 'list' && previous.ordered === ordered) previous.items.push(item)
      else blocks.push({ kind: 'list', ordered, items: [item] })
    } else if (line.trim() === '') {
      flush()
    } else {
      paragraph.push(line.trim())
    }
  }
  flush()
  return blocks
}

/** Citation numbers in the order they first appear. */
export function citedNumbers(text: string): number[] {
  const seen = new Set<number>()
  for (const match of text.matchAll(/\[(\d+)\]/g)) seen.add(Number(match[1]))
  return [...seen]
}
