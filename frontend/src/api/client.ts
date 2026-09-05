const BASE = '';

/**
 * `apiFetch`, plus the response headers.
 *
 * Exists because `GET /api/hats` reports the unpaginated size in
 * `X-Total-Count` and nothing could read it: the header was added so a
 * truncated whole-collection fetch would stop looking like a complete one, and
 * then the only client helper discarded the response object. A separate fetch
 * wrapper would have been a second copy of the 401-redirect and error-body
 * handling below — the half that would drift is the security half — so
 * `apiFetch` delegates here rather than the other way round.
 */
export async function apiFetchWithHeaders<T>(
  path: string, init?: RequestInit,
): Promise<{ data: T; headers: Headers }> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  });
  if (resp.status === 401 && !path.startsWith('/api/auth/') && !path.startsWith('/api/public/')) {
    // Session expired or not logged in — bounce to the login screen unless
    // we're already somewhere public.
    const here = window.location.pathname;
    if (here !== '/login' && !here.startsWith('/share/')) {
      // Carry where we were so login can put you back. This matters most for
      // physical tags: tapping an NFC tag on a hat with an expired session
      // otherwise drops you on the home page, having silently lost the one
      // piece of information the tap carried — which hat you were holding.
      const next = here + window.location.search;
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
    }
    throw new Error('Authentication required');
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(body.detail || `API error ${resp.status}`);
  }
  if (resp.status === 204) return { data: undefined as T, headers: resp.headers };
  return { data: await resp.json(), headers: resp.headers };
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  return (await apiFetchWithHeaders<T>(path, init)).data;
}
