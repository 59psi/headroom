import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
// `vitest/config` re-exports vite's defineConfig with the `test` block typed,
// so the test run inherits the plugins and the __APP_VERSION__/__BUILD_SHA__
// defines rather than needing a second, drifting config.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Bake the package.json version into the bundle as `__APP_VERSION__`. The
// Footer reads it so the running build is always self-identifying.
// `import.meta.dirname`, not `__dirname`: this config is ESM ("type": "module")
// and Vite's upcoming native config loader evaluates it without the CJS shims,
// so `__dirname` becomes a ReferenceError there. Needs Node 20.11+; every Node
// package.json's `engines` accepts (22.22.2+ / 24.15+ / 26+) is past that.
const pkg = JSON.parse(
  readFileSync(resolve(import.meta.dirname, 'package.json'), 'utf-8'),
) as { version: string }

// Build identifier for `__BUILD_SHA__`: the HEADROOM_BUILD_SHA env/build-arg
// wins (Docker builds have no .git), then git's own answer for this checkout.
// Empty when neither is available; the Footer hides it.
//
// `git describe --dirty`, not `git rev-parse --short HEAD`: a tree with
// uncommitted changes reads `a1b2c3d-dirty`, as `scripts/stamp-build.sh`
// stamps it. The rev-parse fallback stamped an edited bare-metal build with
// the clean commit it started from, so the footer named a commit the running
// code was not. `--always` answers with the commit where no tag describes it,
// and `--exclude=*` makes that every time: the stamp is a commit, never a
// release name. Exported, with `cwd`, for `src/test/buildSha.test.ts`.
export function buildSha(cwd?: string): string {
  if (process.env.HEADROOM_BUILD_SHA) return process.env.HEADROOM_BUILD_SHA
  try {
    return execFileSync('git', ['describe', '--always', '--dirty', '--exclude=*'], {
      cwd,
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
  build: {
    // Never inline a font. Vite inlines any asset under 4 KiB as a `data:` URL,
    // and one @fontsource subset is small enough to qualify — but the app's
    // CSP is `font-src 'self'`, which a `data:` font is not, so the browser
    // refused it on every page (a console error each load, and that subset's
    // glyphs fell back to a system face). Served as a file it is same-origin.
    // Everything else keeps the default size rule.
    assetsInlineLimit: filePath => (/\.(woff2?|ttf|otf|eot)$/i.test(filePath) ? false : undefined),
    // The React / router / query runtime as its own chunk. The app was one
    // 652 KB script that a phone downloaded whole before its first paint, and
    // re-downloaded whole on every release although the framework half of it
    // changes only on a dependency bump. Split out, that half stays cached
    // across releases; the app's own pages load on demand (React.lazy in
    // App.tsx, the cropper in PhotoCapture). `chunkSizeWarningLimit` is left
    // at Vite's default on purpose — the warning is a signal, not noise to
    // raise the bar on.
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'framework',
              test: /[\\/]node_modules[\\/](react|react-dom|react-router|scheduler|@tanstack)[\\/]/,
            },
          ],
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Component styling lives in plain .css imported by main.tsx, which the
    // tests never mount — parsing it would cost time and assert nothing.
    css: false,
    restoreMocks: true,
  },
})
