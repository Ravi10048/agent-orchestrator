/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend base URL for split deploys (e.g. https://my-api.onrender.com). Empty → same-origin (local). */
  readonly VITE_API_URL?: string;
}
