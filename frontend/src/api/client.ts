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
      window.location.assign('/login');
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
