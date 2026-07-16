/// <reference types="vite/client" />

// Injected by vite.config.ts via `define` — package.json version baked into
// the bundle at build time so the Footer can self-identify.
declare const __APP_VERSION__: string;

// Git short SHA (or CI-provided HEADROOM_BUILD_SHA); empty string when the
// build environment has neither.
declare const __BUILD_SHA__: string;
