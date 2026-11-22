import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { answerChunks, jsonResponse, RESULT, sse, sseResponse } from './test/fakeServer'

const HEALTH = { status: 'ok', version: '0.2.0', env: 'dev', llm_provider: 'ollama' }

function mockApi(stream: (signal?: AbortSignal) => Response) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input)
    if (url.endsWith('/health')) return Promise.resolve(jsonResponse(HEALTH))
    if (url.endsWith('/ask/stream')) return Promise.resolve(stream(init?.signal ?? undefined))
    return Promise.reject(new Error(`unexpected ${url}`))
  })
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

async function askQuestion(text = 'How should I design for failure?') {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Your question'), `${text}{Enter}`)
  return user
}

describe('App', () => {
  it('shows which provider the API uses', async () => {
    mockApi(() => sseResponse(answerChunks()))
    render(<App />)
    expect(await screen.findByText('ollama')).toBeInTheDocument()
  })

  it('streams an answer with clickable citations, sources and metrics', async () => {
    mockApi(() => sseResponse(answerChunks()))
    render(<App />)
    const user = await askQuestion()

    await screen.findByText('llama3.2')
    expect(screen.getByText('component failures').tagName).toBe('STRONG')

    // [1] was retrieved: a button that highlights source 1
    await user.click(screen.getByRole('button', { name: 'Show source 1' }))
    expect(document.getElementById('source-1')).toHaveClass('active')

    // [7] was never retrieved: flagged, not clickable
    const invalid = screen.getByTitle('Not one of the retrieved sources')
    expect(invalid).toHaveTextContent('7')
    expect(invalid.tagName).toBe('SPAN')

    // source 2 was retrieved but not cited
    const sources = screen.getByRole('region', { name: 'Sources' })
    expect(within(sources).getByText('not cited')).toBeInTheDocument()
    expect(document.getElementById('source-2')).toHaveClass('uncited')

    expect(screen.getByText('1,055 in / 220 out')).toBeInTheDocument()
    expect(screen.getByText('$0 (local)')).toBeInTheDocument()
  })

  it('says so when nothing in the knowledge base is close enough', async () => {
    const notFound = {
      ...RESULT,
      answer: "I don't know.",
      citations: [],
      answered_from_context: false,
    }
    mockApi(() => sseResponse([sse('sources', []), sse('done', notFound)]))
    render(<App />)
    await askQuestion("What's the weather today?")
    expect(await screen.findByText(/nothing close enough/)).toBeInTheDocument()
  })

  it('shows a server error', async () => {
    mockApi(() =>
      sseResponse([
        sse('sources', []),
        sse('error', { detail: 'answering is temporarily unavailable' }),
      ]),
    )
    render(<App />)
    await askQuestion()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'answering is temporarily unavailable',
    )
  })

  it('Stop aborts the request and keeps the partial answer', async () => {
    let release = () => {}
    const gate = new Promise<void>((resolve) => (release = resolve))
    const fetchMock = mockApi((signal) =>
      sseResponse(
        [sse('sources', []) + sse('token', { text: 'Partial answer' }), sse('done', RESULT)],
        gate,
        signal,
      ),
    )
    render(<App />)
    const user = await askQuestion()

    await screen.findByText('Partial answer')
    await user.click(screen.getByRole('button', { name: 'Stop' }))
    release()

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Stopped.'))
    expect(screen.getByText('Partial answer')).toBeInTheDocument()
    const init = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/ask/stream'))?.[1]
    expect(init?.signal?.aborted).toBe(true)
  })

  it('does not send questions shorter than the API accepts', async () => {
    const fetchMock = mockApi(() => sseResponse(answerChunks()))
    render(<App />)
    await askQuestion('hi')
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/ask/stream'))).toBe(false)
  })
})
