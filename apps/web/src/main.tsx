import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from 'react-oidc-context'
import './index.css'
import App from './App.tsx'
import { AuthGate } from './components/AuthGate.tsx'
import { loadRuntimeEnv, oidcSettings, readAuthConfig } from './lib/auth.ts'

async function start(): Promise<void> {
  // Runtime settings from the container win over build-time ones (Phase 6).
  const env = { ...import.meta.env, ...(await loadRuntimeEnv()) }
  const config = readAuthConfig(env, window.location.origin)

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
}

void start()
