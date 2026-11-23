// Sign-in with Amazon Cognito (OpenID Connect, authorization code flow + PKCE).
//
// None of these values are secrets: a public client has no secret, and the IDs
// are visible in the browser anyway. Security comes from the API checking every
// access token, not from hiding configuration.

import { WebStorageStateStore } from 'oidc-client-ts'
import type { AuthProviderProps } from 'react-oidc-context'

export interface AuthConfig {
  /** https://cognito-idp.<region>.amazonaws.com/<user pool id>: where OIDC discovery starts */
  authority: string
  clientId: string
  /** https://<prefix>.auth.<region>.amazoncognito.com: the managed login domain */
  domain: string
  /** Where Cognito sends the browser back; must match the app client exactly. */
  redirectUri: string
}

type Env = Partial<
  Record<'VITE_COGNITO_AUTHORITY' | 'VITE_COGNITO_CLIENT_ID' | 'VITE_COGNITO_DOMAIN', string>
>

/** Returns null when sign-in isn't configured (tests, demo mode). */
export function readAuthConfig(env: Env, origin: string): AuthConfig | null {
  const authority = env.VITE_COGNITO_AUTHORITY?.trim()
  const clientId = env.VITE_COGNITO_CLIENT_ID?.trim()
  const domain = env.VITE_COGNITO_DOMAIN?.trim()
  if (!authority || !clientId || !domain) return null
  return { authority, clientId, domain: domain.replace(/\/$/, ''), redirectUri: `${origin}/` }
}

export function oidcSettings(config: AuthConfig): AuthProviderProps {
  return {
    authority: config.authority,
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    post_logout_redirect_uri: config.redirectUri,
    response_type: 'code', // + PKCE, which oidc-client-ts adds automatically
    scope: 'openid email profile',
    // Tokens live in sessionStorage: gone when the tab closes, readable by any
    // script on the page. That's why the UI never runs model output as HTML (2b).
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    // Uses the refresh token shortly before the 60-minute access token expires.
    automaticSilentRenew: true,
    // After sign-in Cognito returns to /?code=...&state=...; remove them from the
    // address bar so a reload or a shared link doesn't replay them.
    onSigninCallback: () => {
      window.history.replaceState({}, document.title, window.location.pathname)
    },
  }
}

/**
 * Cognito's sign-out endpoint. It isn't in Cognito's OIDC discovery document,
 * so the library can't find it on its own: we build the URL ourselves.
 */
export function cognitoLogoutUrl(config: AuthConfig): string {
  const params = new URLSearchParams({ client_id: config.clientId, logout_uri: config.redirectUri })
  return `${config.domain}/logout?${params.toString()}`
}

/** What the rest of the app needs to know about the signed-in session. */
export interface Session {
  email: string
  getAccessToken: () => string | undefined
  signIn: () => void
  signOut: () => void
}
