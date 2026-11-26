import { describe, expect, it } from 'vitest'
import { cognitoLogoutUrl, loadRuntimeEnv, oidcSettings, readAuthConfig } from './auth'

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

describe('loadRuntimeEnv', () => {
  const respond = (body: string, contentType: string, status = 200) =>
    (() =>
      Promise.resolve(
        new Response(body, { status, headers: { 'content-type': contentType } }),
      )) as unknown as typeof fetch

  it('takes known, non-empty keys from /config.json', async () => {
    const body = JSON.stringify({
      VITE_COGNITO_AUTHORITY: ' https://issuer ',
      VITE_COGNITO_CLIENT_ID: '',
      VITE_COGNITO_DOMAIN: 'https://login',
      SOMETHING_ELSE: 'ignored',
    })
    await expect(loadRuntimeEnv(respond(body, 'application/json'))).resolves.toEqual({
      VITE_COGNITO_AUTHORITY: 'https://issuer',
      VITE_COGNITO_DOMAIN: 'https://login',
    })
  })

  it('ignores a missing file, the dev server HTML fallback, bad JSON and network errors', async () => {
    await expect(loadRuntimeEnv(respond('nope', 'text/plain', 404))).resolves.toEqual({})
    await expect(loadRuntimeEnv(respond('<!doctype html>', 'text/html'))).resolves.toEqual({})
    await expect(loadRuntimeEnv(respond('{bad', 'application/json'))).resolves.toEqual({})
    await expect(loadRuntimeEnv(respond('"text"', 'application/json'))).resolves.toEqual({})
    const failing = (() => Promise.reject(new Error('offline'))) as unknown as typeof fetch
    await expect(loadRuntimeEnv(failing)).resolves.toEqual({})
  })

  it('runtime values override build-time ones', async () => {
    const body = JSON.stringify({
      VITE_COGNITO_AUTHORITY: 'https://runtime-issuer',
      VITE_COGNITO_CLIENT_ID: 'runtime-client',
      VITE_COGNITO_DOMAIN: 'https://runtime-login',
    })
    const env = { ...ENV, ...(await loadRuntimeEnv(respond(body, 'application/json'))) }
    expect(readAuthConfig(env, 'https://kb.example.com')?.clientId).toBe('runtime-client')
  })
})
