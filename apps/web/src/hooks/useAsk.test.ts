import { describe, expect, it } from 'vitest'
import { initialState, isBusy, reducer } from './useAsk'
import { RESULT, SOURCES } from '../test/fakeServer'

describe('reducer', () => {
  it('moves through retrieving → generating → done', () => {
    let state = reducer(initialState, { type: 'start', question: 'Q?' })
    expect(state.status).toBe('retrieving')
    state = reducer(state, { type: 'sources', sources: SOURCES })
    expect(state.status).toBe('generating')
    state = reducer(state, { type: 'token', text: 'Hel' })
    state = reducer(state, { type: 'token', text: 'lo' })
    expect(state.text).toBe('Hello')
    state = reducer(state, { type: 'done', result: RESULT })
    expect(state).toMatchObject({ status: 'done', text: RESULT.answer, result: RESULT })
  })

  it('starting a new question clears the previous answer', () => {
    const old = {
      ...initialState,
      status: 'done' as const,
      text: 'old',
      sources: SOURCES,
      result: RESULT,
    }
    expect(reducer(old, { type: 'start', question: 'New?' })).toEqual({
      ...initialState,
      status: 'retrieving',
      question: 'New?',
    })
  })

  it('keeps the partial answer when stopped', () => {
    const generating = { ...initialState, status: 'generating' as const, text: 'Partial' }
    expect(reducer(generating, { type: 'stopped' })).toMatchObject({
      status: 'stopped',
      text: 'Partial',
    })
  })
})

it('isBusy is true only while retrieving or generating', () => {
  expect(
    ['idle', 'retrieving', 'generating', 'done', 'error', 'stopped'].map((s) => isBusy(s as never)),
  ).toEqual([false, true, true, false, false, false])
})
