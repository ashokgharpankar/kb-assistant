/// <reference types="vite/client" />

// Build-time settings. Vite only exposes variables that start with VITE_, and
// everything exposed ends up in the browser bundle: never put a secret here.
interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  readonly VITE_COGNITO_AUTHORITY?: string
  readonly VITE_COGNITO_CLIENT_ID?: string
  readonly VITE_COGNITO_DOMAIN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
