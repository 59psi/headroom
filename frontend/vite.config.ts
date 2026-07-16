import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Bake the package.json version into the bundle as `__APP_VERSION__`. The
// Footer reads it so the running build is always self-identifying.
const pkg = JSON.parse(
  readFileSync(resolve(__dirname, 'package.json'), 'utf-8'),
) as { version: string }

// Build identifier for `__BUILD_SHA__`: the HEADROOM_BUILD_SHA env/build-arg
// wins (Docker builds have no .git), then the local git short SHA. Empty when
// neither is available; the Footer hides it.
function buildSha(): string {
  if (process.env.HEADROOM_BUILD_SHA) return process.env.HEADROOM_BUILD_SHA
  try {
    return execFileSync('git', ['rev-parse', '--short', 'HEAD'], {
      stdio: ['ignore', 'pipe', 'ignore'],
    })
      .toString()
      .trim()
  } catch {
    return ''
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __BUILD_SHA__: JSON.stringify(buildSha()),
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
    },
  },
})
