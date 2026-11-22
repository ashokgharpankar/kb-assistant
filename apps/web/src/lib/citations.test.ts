import { describe, expect, it } from 'vitest'
import { citedNumbers, parseBlocks, parseInlines } from './citations'

describe('parseInlines', () => {
  it('finds bold text and numeric citations, leaving other brackets as text', () => {
    expect(parseInlines('Use **AZs** [1][2] and [REL11-BP01].')).toEqual([
      { kind: 'text', text: 'Use ' },
      { kind: 'bold', text: 'AZs' },
      { kind: 'text', text: ' ' },
      { kind: 'cite', number: 1 },
      { kind: 'cite', number: 2 },
      { kind: 'text', text: ' and [REL11-BP01].' },
    ])
  })

  it('treats HTML in the model output as plain text', () => {
    expect(parseInlines('<img src=x onerror=alert(1)>')).toEqual([
      { kind: 'text', text: '<img src=x onerror=alert(1)>' },
    ])
  })
})

describe('parseBlocks', () => {
  it('groups lines into paragraphs and lists', () => {
    const blocks = parseBlocks('Intro line\ncontinues.\n\n* one\n- two\n1. first\n2) second\nOutro')
    expect(blocks.map((b) => b.kind)).toEqual(['paragraph', 'list', 'list', 'paragraph'])
    expect(blocks[0]).toEqual({
      kind: 'paragraph',
      inlines: [{ kind: 'text', text: 'Intro line continues.' }],
    })
    expect(blocks[1]).toMatchObject({
      ordered: false,
      items: [[{ text: 'one' }], [{ text: 'two' }]],
    })
    expect(blocks[2]).toMatchObject({
      ordered: true,
      items: [[{ text: 'first' }], [{ text: 'second' }]],
    })
  })

  it('renders a half-written answer (streaming) without errors', () => {
    expect(parseBlocks('* Expect **compo')).toEqual([
      { kind: 'list', ordered: false, items: [[{ kind: 'text', text: 'Expect **compo' }]] },
    ])
  })
})

describe('citedNumbers', () => {
  it('lists each citation once, in order of appearance', () => {
    expect(citedNumbers('a [3] b [1][3] c [2]')).toEqual([3, 1, 2])
  })
})
