import { useCallback, useEffect, useReducer, useRef } from 'react'
import { askStream } from '../lib/api'
import type { AskResult, Source } from '../lib/types'

/**
 * idle → retrieving → generating → done
 *                   ↘ error / stopped (from either busy state)
 */
export type AskStatus = 'idle' | 'retrieving' | 'generating' | 'done' | 'error' | 'stopped'

export interface AskState {
  status: AskStatus
  question: string
  sources: Source[]
  text: string
  result: AskResult | null
  error: string | null
}

type Action =
  | { type: 'start'; question: string }
  | { type: 'sources'; sources: Source[] }
  | { type: 'token'; text: string }
  | { type: 'done'; result: AskResult }
  | { type: 'error'; error: string }
  | { type: 'stopped' }

export const initialState: AskState = {
  status: 'idle',
  question: '',
  sources: [],
  text: '',
  result: null,
  error: null,
}

export function reducer(state: AskState, action: Action): AskState {
  switch (action.type) {
    case 'start':
      return { ...initialState, status: 'retrieving', question: action.question }
    case 'sources':
      return { ...state, status: 'generating', sources: action.sources }
    case 'token':
      return { ...state, text: state.text + action.text }
    case 'done':
      // The final text is the server's: it matches the citations exactly.
      return { ...state, status: 'done', result: action.result, text: action.result.answer }
    case 'error':
      return { ...state, status: 'error', error: action.error }
    case 'stopped':
      return { ...state, status: 'stopped' }
  }
}

export const isBusy = (status: AskStatus) => status === 'retrieving' || status === 'generating'

export function useAsk() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const controller = useRef<AbortController | null>(null)

  const stop = useCallback(() => {
    controller.current?.abort()
  }, [])

  const ask = useCallback(async (question: string) => {
    controller.current?.abort() // a new question cancels the one in flight
    const current = new AbortController()
    controller.current = current
    dispatch({ type: 'start', question })

    try {
      for await (const event of askStream(question, current.signal)) {
        if (event.type === 'sources') dispatch({ type: 'sources', sources: event.sources })
        else if (event.type === 'token') dispatch({ type: 'token', text: event.text })
        else if (event.type === 'done') dispatch({ type: 'done', result: event.result })
        else dispatch({ type: 'error', error: event.detail })
      }
    } catch (err) {
      if (current.signal.aborted) {
        // Only report "stopped" for the request the user stopped, not one replaced by a new question.
        if (controller.current === current) dispatch({ type: 'stopped' })
      } else {
        dispatch({ type: 'error', error: err instanceof Error ? err.message : String(err) })
      }
    } finally {
      if (controller.current === current) controller.current = null
    }
  }, [])

  useEffect(() => () => controller.current?.abort(), []) // leaving the page stops the answer

  return { state, ask, stop }
}
