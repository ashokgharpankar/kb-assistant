import { useAuth } from 'react-oidc-context'
import { cognitoLogoutUrl, type AuthConfig, type Session } from '../lib/auth'

interface Props {
  config: AuthConfig
  children: (session: Session) => React.ReactNode
}

/** Shows the sign-in screen until there is a signed-in user, then renders the app. */
export function AuthGate({ config, children }: Props) {
  const auth = useAuth()

  if (auth.isLoading || auth.activeNavigator) {
    return <p className="auth-screen">Signing in…</p>
  }

  if (auth.error) {
    return (
      <div className="auth-screen">
        <p role="alert">Sign-in failed: {auth.error.message}</p>
        <button type="button" onClick={() => void auth.signinRedirect()}>
          Try again
        </button>
      </div>
    )
  }

  if (!auth.isAuthenticated || !auth.user) {
    return (
      <div className="auth-screen">
        <h1>KB Assistant</h1>
        <p>Sign in to ask questions about the AWS Well-Architected Framework.</p>
        <button type="button" onClick={() => void auth.signinRedirect()}>
          Sign in
        </button>
      </div>
    )
  }

  // A silent renewal replaces auth.user and re-renders this component, so the
  // next request always gets the fresh token.
  const { user } = auth
  const session: Session = {
    email: String(user.profile.email ?? user.profile.sub),
    getAccessToken: () => user.access_token,
    signIn: () => void auth.signinRedirect(),
    signOut: () => {
      // Forget the tokens here, then end the Cognito session too; otherwise the
      // next "Sign in" would skip the password because Cognito still remembers you.
      void auth.removeUser().then(() => window.location.assign(cognitoLogoutUrl(config)))
    },
  }
  return <>{children(session)}</>
}
