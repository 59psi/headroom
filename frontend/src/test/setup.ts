// Registers the jest-dom matchers (toBeInTheDocument, toHaveValue, …) on
// vitest's `expect`, and unmounts between tests so a leaked component from one
// test can't be found by the next one's queries.
import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(cleanup);
