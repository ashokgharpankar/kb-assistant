import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { Session } from './lib/auth'
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

function session(overrides: Partial<Session> = {}): Session {
  return {
    email: 'ashok@example.com',
    getAccessToken: () => 'token-1',
    signIn: vi.fn(),
    signOut: vi.fn(),
    ...overrides,
  }
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
    render(<App session={null} />)
    expect(await screen.findByText('ollama')).toBeInTheDocument()
  })

  it('streams an answer with clickable citations, sources and metrics', async () => {
    mockApi(() => sseResponse(answerChunks()))
    render(<App session={null} />)
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
    render(<App session={null} />)
    await askQuestion("What's the weather today?")
    expect(await screen.findByText(/nothing close enough/)).toBeInTheDocument()
  })

  it('warns when the answer names something no source contains', async () => {
    const weak = { ...RESULT, grounding_score: 1, unknown_terms: ['LRS'] }
    mockApi(() =>
      sseResponse([sse('sources', []), sse('token', { text: 'Pick LRS [1].' }), sse('done', weak)]),
    )
    render(<App session={null} />)
    await askQuestion('Which S3 redundancy option should I pick?')
    expect(await screen.findByRole('note')).toHaveTextContent('not in any source: LRS')
  })

  it('shows no grounding warning for a well-supported answer', async () => {
    mockApi(() =>
      sseResponse([
        sse('sources', []),
        sse('token', { text: 'Use AZs [1].' }),
        sse('done', { ...RESULT, grounding_score: 1, unknown_terms: [] }),
      ]),
    )
    render(<App session={null} />)
    await askQuestion()
    await screen.findByText(/in \/ 220 out/)
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('labels an answer served from the cache', async () => {
    const hit = { ...RESULT, cache: 'semantic', cache_similarity: 0.981, cost_usd: '0' }
    mockApi(() =>
      sseResponse([sse('sources', []), sse('token', { text: 'Use AZs [1].' }), sse('done', hit)]),
    )
    render(<App session={null} />)
    await askQuestion()
    expect(await screen.findByText('From cache (similar question, 98%)')).toBeInTheDocument()
    expect(screen.getByText('$0 (cached)')).toBeInTheDocument()
  })

  it('shows a server error', async () => {
    mockApi(() =>
      sseResponse([
        sse('sources', []),
        sse('error', { detail: 'answering is temporarily unavailable' }),
      ]),
    )
    render(<App session={null} />)
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
    render(<App session={null} />)
    const user = await askQuestion()

    await screen.findByText('Partial answer')
    await user.click(screen.getByRole('button', { name: 'Stop' }))
    release()

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Stopped.'))
    expect(screen.getByText('Partial answer')).toBeInTheDocument()
    const init = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/ask/stream'))?.[1]
    expect(init?.signal?.aborted).toBe(true)
  })

  it("sends the signed-in user's token and shows who is signed in", async () => {
    const fetchMock = mockApi(() => sseResponse(answerChunks()))
    const signOut = vi.fn()
    render(<App session={session({ signOut })} />)
    expect(screen.getByText('ashok@example.com')).toBeInTheDocument()

    const user = await askQuestion()
    await screen.findByText('llama3.2')
    const init = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/ask/stream'))?.[1]
    expect((init!.headers as Record<string, string>).Authorization).toBe('Bearer token-1')

    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(signOut).toHaveBeenCalled()
  })

  it('offers to sign in again when the API says 401', async () => {
    mockApi(() => jsonResponse({ detail: 'invalid or expired token' }, 401))
    const signIn = vi.fn()
    render(<App session={session({ signIn })} />)
    const user = await askQuestion()
    await user.click(await screen.findByRole('button', { name: 'Sign in again' }))
    expect(signIn).toHaveBeenCalled()
  })

  it('explains a 401 when this page has no sign-in settings', async () => {
    mockApi(() => jsonResponse({ detail: 'sign in required' }, 401))
    render(<App session={null} />)
    await askQuestion()
    expect(await screen.findByRole('alert')).toHaveTextContent('apps/web/.env.local')
  })

  it('does not send questions shorter than the API accepts', async () => {
    const fetchMock = mockApi(() => sseResponse(answerChunks()))
    render(<App session={null} />)
    await askQuestion('hi')
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/ask/stream'))).toBe(false)
  })
})
