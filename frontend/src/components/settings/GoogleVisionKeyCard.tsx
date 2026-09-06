import {
  getGoogleVisionKeyStatus, setGoogleVisionKey, deleteGoogleVisionKey,
} from '../../api/settings';
import { KeyCard, type KeyProviderSpec } from './KeyCard';

const GOOGLE_VISION: KeyProviderSpec = {
  title: 'Google Vision Key (fallback)',
  queryKey: ['settings', 'google-vision-key'],
  getStatus: getGoogleVisionKeyStatus,
  setKey: setGoogleVisionKey,
  deleteKey: deleteGoogleVisionKey,
  inputId: 'google-vision-key',
  placeholder: 'AIzaSy...',
  noKeyText: 'No key configured — fallback provides colors only.',
  removeConfirm: 'Remove Google Vision key?',
  blurb: (
    <>
      Optional. When Claude is unavailable, hats still get color swatches from the
      photo cutout — add a Google Cloud Vision API key to also detect the brand
      from its logo. Create one at{' '}
      <a href="https://console.cloud.google.com/apis/library/vision.googleapis.com" target="_blank" rel="noopener noreferrer">
        console.cloud.google.com
      </a>{' '}
      (enable the Cloud Vision API, then create an API key).
    </>
  ),
};

export function GoogleVisionKeyCard() {
  return <KeyCard provider={GOOGLE_VISION} />;
}
