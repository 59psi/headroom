import { useQuery } from '@tanstack/react-query';
import { getApiKeyStatus, setApiKey, deleteApiKey, testApiKey, getModel } from '../../api/settings';
import { KeyCard, type KeyProviderSpec } from './KeyCard';

const ANTHROPIC: Omit<KeyProviderSpec, 'test'> = {
  title: 'Claude API Key',
  queryKey: ['settings', 'api-key'],
  getStatus: getApiKeyStatus,
  setKey: setApiKey,
  deleteKey: deleteApiKey,
  inputId: 'anthropic-key',
  placeholder: 'sk-ant-...',
  noKeyText: 'No key configured.',
  removeConfirm: 'Remove API key?',
  featured: true,
  blurb: (
    <>
      Required for AI hat analysis (brand, model, colors, price). Stored locally in
      this app's database. Get a key at{' '}
      <a href="https://console.anthropic.com/" target="_blank" rel="noopener noreferrer">
        console.anthropic.com
      </a>.
    </>
  ),
};

export function AnthropicKeyCard() {
  // A test result is only meaningful for the model it ran against, so the
  // card drops it whenever the active model changes — including when the
  // Model card below changes it.
  const model = useQuery({ queryKey: ['settings', 'model'], queryFn: getModel });
  return <KeyCard provider={{ ...ANTHROPIC, test: { run: testApiKey, resetOn: model.data?.model_id } }} />;
}
