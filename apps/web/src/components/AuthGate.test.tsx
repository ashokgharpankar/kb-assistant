import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AuthContextProps } from 'react-oidc-context'
import { AuthGate } from './AuthGate'
import type { AuthConfig, Session } from '../lib/auth'

let auth: Partial<AuthContextProps>
vi.mock('react-oidc-context', () => ({ useAuth: () => auth }))

const CONFIG: AuthConfig = {
  authority: 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Pool',
  clientId: 'client123',
  domain: 'https://kb.auth.us-east-1.amazoncognito.com',
  redirectUri: 'http://localhost:5173/',
}

function renderGate() {
  let session: Session | undefined
  render(
    <AuthGate config={CONFIG}>
      {(s) => {
        session = s
        return <p>the app</p>
      }}
    </AuthGate>,
  )
  return () => session
}

beforeEach(() => {
  auth = {
    isLoading: false,
    isAuthenticated: false,
    signinRedirect: vi.fn(() => Promise.resolve()),
  }
})

describe('AuthGate', () => {
  it('shows a sign-in screen, and Sign in starts the redirect to Cognito', async () => {
    renderGate()
    expect(screen.queryByText('the app')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(auth.signinRedirect).toHaveBeenCalled()
  })

  it('waits while the sign-in callback is processed', () => {
    auth = { ...auth, isLoading: true }
    renderGate()
    expect(screen.getByText('Signing in…')).toBeInTheDocument()
  })

  it('shows a sign-in error with a retry', () => {
    auth = {
      ...auth,
      error: Object.assign(new Error('invalid_grant'), { source: 'signinCallback' as const }),
    }
    renderGate()
    expect(screen.getByRole('alert')).toHaveTextContent('invalid_grant')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('renders the app with the session once signed in', async () => {
    const removeUser = vi.fn(() => Promise.resolve())
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    auth = {
      ...auth,
      isAuthenticated: true,
      removeUser,
      user: {
        access_token: 'token-1',
        profile: { sub: 'u1', email: 'ashok@example.com' },
      } as never,
    }
    const session = renderGate()

    expect(screen.getByText('the app')).toBeInTheDocument()
    expect(session()?.email).toBe('ashok@example.com')
    expect(session()?.getAccessToken()).toBe('token-1')

    session()?.signOut()
    await vi.waitFor(() => expect(assign).toHaveBeenCalled())
    expect(removeUser).toHaveBeenCalled()
    expect(assign.mock.calls[0]?.[0]).toContain('/logout?client_id=client123')
    vi.unstubAllGlobals()
  })
})
