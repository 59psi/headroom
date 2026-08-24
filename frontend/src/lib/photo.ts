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
export function tileSrc(hat: { thumb_path: string | null; photo_path: string | null }): string {
  return `/uploads/${hat.thumb_path ?? hat.photo_path}`;
}
