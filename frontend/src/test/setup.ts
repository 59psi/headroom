// Registers the jest-dom matchers (toBeInTheDocument, toHaveValue, …) on
// vitest's `expect`, and unmounts between tests so a leaked component from one
// test can't be found by the next one's queries.
import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import { installMatchMedia, resetViewportWidth } from './matchMedia';

// jsdom has no CSS engine and therefore no `window.matchMedia`, so anything
// asking about the viewport throws on mount. The stub answers "no match" until
// a test calls `setViewportWidth`, which is the mobile-first base case.
installMatchMedia();

// Object URLs, the way every browser this app runs in has them. jsdom has
// none of its own; vitest's jsdom environment fills the gap with a shim that
// reads a private field of jsdom's Blob (`_buffer`), and jsdom 30.1 moved that
// field — so the shim threw inside the change handler, every "pick a photo"
// path stopped before its upload, and five upload tests failed with the app
// code unchanged. A test environment that breaks on a patch release of a
// dependency's internals is the mechanism at fault, so the tests get a
// deterministic pair of their own instead. The URLs are never loaded (jsdom
// fetches no images); tests that assert a particular URL still install their
// own, restoring this one after.
let objectUrls = 0;
URL.createObjectURL = () => `blob:test/${++objectUrls}`;
URL.revokeObjectURL = () => {};

afterEach(() => {
  cleanup();
  resetViewportWidth();
});
