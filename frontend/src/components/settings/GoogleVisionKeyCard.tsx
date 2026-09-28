import {
  getGoogleVisionKeyStatus, setGoogleVisionKey, deleteGoogleVisionKey,
} from '../../api/settings';
import { KeyCard, type KeyProviderSpec } from './KeyCard';

const GOOGLE_VISION: KeyProviderSpec = {
  title: 'Google Vision key',
  queryKey: ['settings', 'google-vision-key'],
  getStatus: getGoogleVisionKeyStatus,
  setKey: setGoogleVisionKey,
  deleteKey: deleteGoogleVisionKey,
  inputId: 'google-vision-key',
  placeholder: 'AIzaSy...',
  envVar: 'HEADROOM_GOOGLE_VISION_API_KEY',
  description: 'Optional fallback: reads the brand from a hat’s logo when Claude is unavailable.',
  noKeyText: 'No key configured — fallback provides colors only.',
  help: (
    <>
      <p>
        When Claude is unavailable, hats still get color swatches from the photo
        cutout — add a Google Cloud Vision API key to also detect the brand from
        its logo. Create one at{' '}
        <a href="https://console.cloud.google.com/apis/library/vision.googleapis.com" target="_blank" rel="noopener noreferrer">
          console.cloud.google.com
        </a>{' '}
        (enable the Cloud Vision API, then create an API key).
      </p>
      <p>
        A key saved here takes precedence over one set in the server environment
        (<code>HEADROOM_GOOGLE_VISION_API_KEY</code>). Google offers no cheap
        probe for this key, so there is no connection test.
      </p>
    </>
  ),
  removeConfirm: 'Remove Google Vision key?',
  removeConsequence: (
    <p>
      The fallback goes back to colors only: brands are no longer read from logos
      when Claude is unavailable.
    </p>
  ),
};

export function GoogleVisionKeyCard() {
  return <KeyCard provider={GOOGLE_VISION} />;
}
