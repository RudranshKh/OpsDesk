import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const securityHeaders = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}

function apiOriginConsistencyPlugin(apiOrigin: string) {
  return {
    name: 'opsdesk-api-origin-consistency',
    transformIndexHtml(html: string) {
      const marker = `<meta name="opsdesk-api-origin" content="${apiOrigin}">`
      return html.replace('</head>', `  ${marker}\n  </head>`)
    },
    configurePreviewServer(server: { config: { root: string; build: { outDir: string } } }) {
      const builtIndex = resolve(server.config.root, server.config.build.outDir, 'index.html')
      let html: string
      try {
        html = readFileSync(builtIndex, 'utf8')
      } catch {
        throw new Error('Vite preview requires a completed OpsDesk production build.')
      }
      const builtOrigin = html.match(/<meta name="opsdesk-api-origin" content="([^"]+)">/)?.[1]
      if (!builtOrigin) {
        throw new Error('The built OpsDesk HTML is missing its API-origin metadata; rebuild it with this Vite configuration.')
      }
      if (builtOrigin !== apiOrigin) {
        throw new Error(
          'VITE_API_BASE_URL does not match the API origin used to build the preview CSP. Rebuild and preview with aligned configuration.',
        )
      }
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const apiBase = env.VITE_API_BASE_URL || 'http://localhost:8000/api'
  const apiOrigin = new URL(apiBase, 'http://localhost').origin
  const previewHeaders = {
    ...securityHeaders,
    'Content-Security-Policy': [
      "default-src 'self'",
      "base-uri 'self'",
      "object-src 'none'",
      "frame-ancestors 'none'",
      "script-src 'self'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self' data:",
      `connect-src 'self' ${apiOrigin}`,
    ].join('; '),
  }

  return {
    plugins: [react(), tailwindcss(), apiOriginConsistencyPlugin(apiOrigin)],
    server: { port: 5173, headers: securityHeaders },
    preview: { headers: previewHeaders },
  }
})
