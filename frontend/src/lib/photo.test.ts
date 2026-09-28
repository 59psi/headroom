import { describe, expect, it } from 'vitest';
import { logoSrc, tileSrc, uploadUrl } from './photo';

describe('tileSrc', () => {
  it('uses the small thumbnail when there is one — a grid of full cutouts is tens of MB', () => {
    expect(tileSrc({ thumb_path: 'hats/5.thumb.webp', photo_path: 'hats/5.png' }))
      .toBe('/uploads/hats/5.thumb.webp');
  });

  it('falls back to the full photo for a hat analyzed before thumbnails existed', () => {
    expect(tileSrc({ thumb_path: null, photo_path: 'hats/5.png' })).toBe('/uploads/hats/5.png');
  });
});

describe('uploadUrl / logoSrc', () => {
  it('serves stored files from the one /uploads mount', () => {
    expect(uploadUrl('hats/5.png')).toBe('/uploads/hats/5.png');
  });

  it('versions the logo so a replaced one is not served from cache', () => {
    expect(logoSrc({ logo_path: 'branding/logo.png', version: 17 })).toBe('/uploads/branding/logo.png?v=17');
    expect(logoSrc({ logo_path: 'branding/logo.png' })).toBe('/uploads/branding/logo.png');
    expect(logoSrc({ logo_path: null })).toBeNull();
  });
});
