import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router';
import { createHat, uploadHatPhoto } from '../api/hats';
import { getApiKeyStatus } from '../api/settings';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { NewCaseModal } from '../components/common/NewCaseModal';
import {
  useHatFormOptions, useHatPhoto, PhotoCard, HatBasicsCard, type HatBasics,
} from '../components/hats/HatFormFields';

export function AddHatPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();

  const [basics, setBasics] = useState<HatBasics>({
    style: 'a_game',
    size: 'classic',
    condition: 'new',
    caseId: searchParams.get('caseId') || '',
    dateLastWorn: '',
  });
  const [showNewCase, setShowNewCase] = useState(false);

  const options = useHatFormOptions();
  const { photo, photoPreview, onCapture } = useHatPhoto();
  const apiKey = useQuery({ queryKey: ['settings', 'api-key'], queryFn: getApiKeyStatus });

  function setBasic<K extends keyof HatBasics>(key: K, value: HatBasics[K]) {
    setBasics(prev => ({ ...prev, [key]: value }));
  }

  const mutation = useMutation({
    mutationFn: async () => {
      const data: Record<string, unknown> = {
        style: basics.style, size: basics.size, condition: basics.condition,
      };
      if (basics.caseId) data.case_id = Number(basics.caseId);
      if (basics.dateLastWorn) data.date_last_worn = basics.dateLastWorn;

      const hat = await createHat(data);
      if (photo) {
        await uploadHatPhoto(hat.id, photo);
      }
      return hat;
    },
    onSuccess: (hat) => {
      qc.invalidateQueries({ queryKey: ['hats'] });
      qc.invalidateQueries({ queryKey: ['cases'] });
      navigate(`/hats/${hat.id}`);
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  if (options.isLoading) return <LoadingSpinner />;

  return (
    <>
      <h1 className="mb-3">Add Hat</h1>

      {photo && apiKey.data && !apiKey.data.configured && (
        <div className="alert alert-warning mb-3">
          No Anthropic API key configured — photo will save, but Claude won't run.
          Set one in <a href="/settings" style={{ color: 'inherit', textDecoration: 'underline' }}>Settings</a> for brand / color / price detection.
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <PhotoCard onCapture={onCapture} previewUrl={photoPreview} />

        <HatBasicsCard
          values={basics}
          onChange={setBasic}
          options={options}
          onCreateCase={() => setShowNewCase(true)}
          caseLabel="Assign to Case (optional)"
          dateLabel="Date Last Worn (optional)"
        />

        {mutation.error && (
          <div className="alert alert-danger">{String(mutation.error)}</div>
        )}

        <button
          type="submit"
          className="btn btn-primary w-100 btn-lg"
          disabled={mutation.isPending}
        >
          {mutation.isPending ? 'Saving · Claude analyzing…' : 'Save Hat'}
        </button>
      </form>

      <NewCaseModal
        show={showNewCase}
        onClose={() => setShowNewCase(false)}
        onCreated={(id) => setBasic('caseId', String(id))}
      />
    </>
  );
}
