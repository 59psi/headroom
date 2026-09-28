import { useQuery } from '@tanstack/react-query';
import { getApiKeyStatus, setApiKey, deleteApiKey, testApiKey, getModel } from '../../api/settings';
import { KeyCard, type KeyProviderSpec } from './KeyCard';

const CONSOLE_LINK = (
  <a href="https://console.anthropic.com/" target="_blank" rel="noopener noreferrer">
    console.anthropic.com
  </a>
);

const ANTHROPIC: Omit<KeyProviderSpec, 'test'> = {
  title: 'Claude API key',
  queryKey: ['settings', 'api-key'],
  getStatus: getApiKeyStatus,
  setKey: setApiKey,
  deleteKey: deleteApiKey,
  inputId: 'anthropic-key',
  placeholder: 'sk-ant-...',
  envVar: 'HEADROOM_ANTHROPIC_API_KEY',
  required: true,
  featured: true,
  description: 'Required for AI hat analysis: brand, model, colors and price.',
  // The link is here as well as in the help because this is the moment it is
  // needed — someone looking at an empty key field is about to go and get one.
  noKeyText: <>No key configured. Get one at {CONSOLE_LINK}.</>,
  help: (
    <>
      <p>
        Stored locally in this app&rsquo;s database. Get a key at {CONSOLE_LINK}.
      </p>
      <p>
        Saving a key tests it straight away, against the model chosen in the
        Claude model card. A key saved here takes precedence over one set in the
        server environment (<code>HEADROOM_ANTHROPIC_API_KEY</code>).
      </p>
      <p>
        Without a key, new photos still get fallback analysis: colors from the
        photo cutout, plus the brand from its logo when a Google Vision key is set.
      </p>
    </>
  ),
  removeConfirm: 'Remove API key?',
  removeConsequence: (
    <p>
      New photos get fallback analysis only — colors, plus a logo brand if
      Google Vision is set up — until a key is added again.
    </p>
  ),
};

export function AnthropicKeyCard() {
  // A test result is only meaningful for the model it ran against, so the
  // card drops it whenever the active model changes — including when the
  // Model card below changes it.
  const model = useQuery({ queryKey: ['settings', 'model'], queryFn: getModel });
  return <KeyCard provider={{ ...ANTHROPIC, test: { run: testApiKey, resetOn: model.data?.model_id } }} />;
}
