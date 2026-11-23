import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from 'react-oidc-context'
import './index.css'
import App from './App.tsx'
import { AuthGate } from './components/AuthGate.tsx'
import { oidcSettings, readAuthConfig } from './lib/auth.ts'

const config = readAuthConfig(import.meta.env, window.location.origin)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {config ? (
      <AuthProvider {...oidcSettings(config)}>
        <AuthGate config={config}>{(session) => <App session={session} />}</AuthGate>
      </AuthProvider>
    ) : (
      // No Cognito settings: demo mode or tests. The API decides whether that's allowed.
      <App session={null} />
    )}
  </StrictMode>,
)
