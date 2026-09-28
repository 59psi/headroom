import { describe, expect, it } from 'vitest';
import { croppedFileName } from './PhotoCropper';

describe('croppedFileName', () => {
  it('names the crop .jpg whatever was picked, since the crop is a JPEG', () => {
    expect(croppedFileName('IMG_0042.HEIC')).toBe('IMG_0042.jpg');
    expect(croppedFileName('hat.png')).toBe('hat.jpg');
    expect(croppedFileName('my.hat.photo.webp')).toBe('my.hat.photo.jpg');
  });

  it('keeps a usable name for a file with none', () => {
    expect(croppedFileName('.heic')).toBe('photo.jpg');
    expect(croppedFileName('')).toBe('photo.jpg');
  });
});
