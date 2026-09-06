import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { createHat, uploadHatPhoto } from '../api/hats';
import { getApiKeyStatus } from '../api/settings';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { NewCaseModal } from '../components/common/NewCaseModal';
import {
  useHatFormOptions, useHatPhoto, PhotoCard, HatBasicsCard,
  DEFAULT_HAT_BASICS, type HatBasics,
} from '../components/hats/HatFormFields';
import { invalidateHatViews, invalidateHatVocabulary } from '../lib/invalidate';

export function AddHatPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();

  const [basics, setBasics] = useState<HatBasics>({
    ...DEFAULT_HAT_BASICS,
    caseId: searchParams.get('caseId') || '',
    roomId: '',
    dateLastWorn: '',
    purchasePrice: '',
    purchasedAt: '',
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
      // Only sent when typed. An empty string would be stored as a real value,
      // making the hat look annotated when nothing was entered — and for
      // `artist_series` would read as an answer where analysis (which CAN fill
      // that one in) should still be free to. Construction is owner-only either
      // way; the blank there is simply "not recorded".
      if (basics.construction.trim()) data.construction = basics.construction.trim();
      if (basics.artistSeries.trim()) data.artist_series = basics.artistSeries.trim();
      if (basics.caseId) data.case_id = Number(basics.caseId);
      // Only when there's no case: a cased hat's room is its case's, and the
      // server ignores this alongside a case anyway.
      else if (basics.roomId) data.room_id = Number(basics.roomId);
      if (basics.limitedEdition) data.limited_edition = true;
      if (basics.dateLastWorn) data.date_last_worn = basics.dateLastWorn;
      if (basics.purchasePrice) data.purchase_price = Number(basics.purchasePrice);
      // Midnight local, matching how `date_last_worn` is sent — the column is
      // a timestamp but only the date is ever entered or displayed.
      if (basics.purchasedAt) data.purchased_at = `${basics.purchasedAt}T00:00:00`;

      const hat = await createHat(data);
      if (photo) {
        await uploadHatPhoto(hat.id, photo);
      }
      return hat;
    },
    onSuccess: (hat) => {
      invalidateHatViews(qc);
      invalidateHatVocabulary(qc);
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
          Set one in <Link to="/settings?tab=analysis" style={{ color: 'inherit', textDecoration: 'underline' }}>Settings</Link> for brand / color / price detection.
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
          {/* No longer "Claude analyzing…": the upload returns as soon as the
              photo is saved and analysis is queued, so claiming otherwise
              would overstate what this button is waiting on. */}
          {mutation.isPending ? 'Saving…' : 'Save Hat'}
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
