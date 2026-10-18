/**
 * Image source for a small hat tile.
 *
 * Cutouts are 1200px transparent PNGs — a few hundred KB to a couple of MB
 * each. Rendering a grid of them at ~160 CSS px meant a fifty-hat gallery
 * pulled tens of megabytes over the wire and decoded far more than that in
 * phone memory, for pixels nobody could see. `thumb_path` is a 320px WebP
 * derivative, typically under 10 KB.
 *
 * Falls back to the full photo: hats analyzed before thumbnails existed have
 * none until the startup backfill reaches them, and a slow tile beats a broken
 * one. Full-size views (the hat page lightbox) deliberately do NOT use this.
 */
export function tileSrc(hat: { thumb_path?: string | null; photo_path: string | null }): string {
  return uploadUrl(hat.thumb_path ?? hat.photo_path);
}

/**
 * Where a stored file is served from. One definition: `/uploads/${…}` was
 * assembled inline in nine components, which is nine places for the mount
 * to drift away from `app.py`.
 */
export function uploadUrl(path: string | null | undefined): string {
  return `/uploads/${path ?? ''}`;
}

/**
 * The site logo's URL, or null when there is none. Versioned: the server
 * writes every logo to the same path, so the bare URL let the nav and the
 * home hero go on showing the cached logo after it was replaced — the one
 * place that did not was the settings card, which bumped a counter of its own.
 */
export function logoSrc(status: { logo_path: string | null; version?: number | null } | undefined): string | null {
  if (!status?.logo_path) return null;
  const v = status.version;
  return `${uploadUrl(status.logo_path)}${v !== null && v !== undefined ? `?v=${v}` : ''}`;
}
