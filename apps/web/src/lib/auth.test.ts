import { describe, expect, it } from 'vitest'
import { cognitoLogoutUrl, oidcSettings, readAuthConfig } from './auth'

const ENV = {
  VITE_COGNITO_AUTHORITY: 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Pool',
  VITE_COGNITO_CLIENT_ID: 'client123',
  VITE_COGNITO_DOMAIN: 'https://kb-assistant-dev-ab12cd34.auth.us-east-1.amazoncognito.com/',
}

describe('readAuthConfig', () => {
  it('is null when sign-in is not configured', () => {
    expect(readAuthConfig({}, 'http://localhost:5173')).toBeNull()
    expect(
      readAuthConfig({ ...ENV, VITE_COGNITO_CLIENT_ID: ' ' }, 'http://localhost:5173'),
    ).toBeNull()
  })

  it('builds the redirect URI from the page origin and trims the domain', () => {
    expect(readAuthConfig(ENV, 'http://localhost:5173')).toEqual({
      authority: ENV.VITE_COGNITO_AUTHORITY,
      clientId: 'client123',
      domain: 'https://kb-assistant-dev-ab12cd34.auth.us-east-1.amazoncognito.com',
      redirectUri: 'http://localhost:5173/',
    })
  })
})

describe('oidcSettings', () => {
  it('uses the code flow with the Cognito pool as authority', () => {
    const config = readAuthConfig(ENV, 'http://localhost:5173')!
    const settings = oidcSettings(config)
    expect(settings).toMatchObject({
      authority: ENV.VITE_COGNITO_AUTHORITY,
      client_id: 'client123',
      redirect_uri: 'http://localhost:5173/',
      response_type: 'code',
      scope: 'openid email profile',
      automaticSilentRenew: true,
    })
  })

  it('removes ?code and ?state from the address bar after sign-in', () => {
    window.history.replaceState({}, '', '/?code=abc&state=xyz')
    const config = readAuthConfig(ENV, 'http://localhost:5173')!
    void oidcSettings(config).onSigninCallback?.(undefined)
    expect(window.location.search).toBe('')
  })
})

it('cognitoLogoutUrl ends the Cognito session and returns to the app', () => {
  const config = readAuthConfig(ENV, 'http://localhost:5173')!
  expect(cognitoLogoutUrl(config)).toBe(
    'https://kb-assistant-dev-ab12cd34.auth.us-east-1.amazoncognito.com/logout' +
      '?client_id=client123&logout_uri=http%3A%2F%2Flocalhost%3A5173%2F',
  )
})
