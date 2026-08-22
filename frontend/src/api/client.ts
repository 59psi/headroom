const BASE = '';

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
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
  if (resp.status === 204) return undefined as T;
  return resp.json();
}
