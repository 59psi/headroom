/**
 * Copy text to the clipboard, on every deployment this app actually has.
 *
 * `navigator.clipboard` exists only in a secure context. Headroom is commonly
 * served over plain HTTP on the LAN (`docker-compose.http80.yml`), where it is
 * `undefined` — so the selection fallback is not a legacy nicety, it is the
 * path most installs take. `TagUrlRow` had this right; the share-link and
 * purchase-prompt copy buttons each called `navigator.clipboard.writeText`
 * bare, so on the http80 overlay one threw and the other silently did nothing.
 *
 * Returns true when SOMETHING copied. `fallbackInput`, when given, is a
 * readonly field holding the same text; selecting it is what makes the legacy
 * `execCommand('copy')` path work, and leaves the text selected for a manual
 * long-press → Copy if even that refuses (older iOS Safari can).
 */
export async function copyText(text: string, fallbackInput?: HTMLInputElement | null): Promise<boolean> {
  try {
    if (window.isSecureContext && navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    if (fallbackInput) {
      fallbackInput.select();
      fallbackInput.setSelectionRange(0, text.length); // iOS ignores select() alone
      return document.execCommand('copy');
    }
    // No field to select from: stage the text in a throwaway one.
    const staging = document.createElement('textarea');
    staging.value = text;
    staging.setAttribute('readonly', '');
    staging.style.position = 'fixed';
    staging.style.opacity = '0';
    document.body.appendChild(staging);
    staging.select();
    staging.setSelectionRange(0, text.length);
    const ok = document.execCommand('copy');
    document.body.removeChild(staging);
    return ok;
  } catch {
    fallbackInput?.select();
    return false;
  }
}
