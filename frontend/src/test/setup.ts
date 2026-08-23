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

afterEach(() => {
  cleanup();
  resetViewportWidth();
});
