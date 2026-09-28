/**
 * The footer's build stamp on a bare-metal build, where no
 * `HEADROOM_BUILD_SHA` is set and `vite.config.ts` asks git itself.
 *
 * It asked `git rev-parse --short HEAD`, which cannot see uncommitted
 * changes: build an edited tree and the footer named the clean commit it
 * started from, while `scripts/stamp-build.sh` — the other way the stamp is
 * made — marks the same tree `-dirty`. Run against a scratch repository, so
 * the answer does not depend on the state of this checkout.
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { buildSha } from '../../vite.config';

let repo: string;

function git(...args: string[]): string {
  // A throwaway identity, and nothing from the machine's git config that
  // could get in the way of a commit (signing, hooks).
  return execFileSync('git', [
    '-c', 'user.name=t', '-c', 'user.email=t@example.com',
    '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null',
    ...args,
  ], { cwd: repo, stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim();
}

beforeEach(() => {
  repo = mkdtempSync(join(tmpdir(), 'headroom-stamp-'));
  git('init', '-q');
  writeFileSync(join(repo, 'file.txt'), 'one\n');
  git('add', 'file.txt');
  git('commit', '-q', '-m', 'one');
  vi.stubEnv('HEADROOM_BUILD_SHA', '');
});

afterEach(() => {
  vi.unstubAllEnvs();
  rmSync(repo, { recursive: true, force: true });
});

describe('buildSha', () => {
  it('stamps a clean tree with its commit', () => {
    expect(buildSha(repo)).toBe(git('rev-parse', '--short', 'HEAD'));
  });

  it('marks a tree with uncommitted changes -dirty, as stamp-build.sh does', () => {
    writeFileSync(join(repo, 'file.txt'), 'two\n');
    expect(buildSha(repo)).toBe(`${git('rev-parse', '--short', 'HEAD')}-dirty`);
  });

  it('is the commit even where a tag describes it, never the tag', () => {
    git('tag', 'v9.9.9');
    expect(buildSha(repo)).toBe(git('rev-parse', '--short', 'HEAD'));
  });

  it('lets HEADROOM_BUILD_SHA win, as a Docker build sets it', () => {
    vi.stubEnv('HEADROOM_BUILD_SHA', 'abc1234');
    expect(buildSha(repo)).toBe('abc1234');
  });
});
