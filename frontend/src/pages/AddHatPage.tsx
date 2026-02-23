import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { createHat, uploadHatPhoto, getStyles, getSizes, getConditions } from '../api/hats';
import { listCases } from '../api/cases';
import { PhotoCapture } from '../components/photos/PhotoCapture';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { NewCaseModal } from '../components/common/NewCaseModal';

export function AddHatPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();

  const [style, setStyle] = useState('a_game');
  const [size, setSize] = useState('classic');
  const [condition, setCondition] = useState('new');
  const [caseId, setCaseId] = useState(searchParams.get('caseId') || '');
  const [dateLastWorn, setDateLastWorn] = useState('');
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [showNewCase, setShowNewCase] = useState(false);

  const styles = useQuery({ queryKey: ['meta', 'styles'], queryFn: getStyles });
  const sizes = useQuery({ queryKey: ['meta', 'sizes'], queryFn: getSizes });
  const conditions = useQuery({ queryKey: ['meta', 'conditions'], queryFn: getConditions });
  const cases = useQuery({ queryKey: ['cases'], queryFn: listCases });

  const mutation = useMutation({
    mutationFn: async () => {
      const data: Record<string, unknown> = { style, size, condition };
      if (caseId) data.case_id = Number(caseId);
      if (dateLastWorn) data.date_last_worn = dateLastWorn;

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

  function handlePhotoCapture(file: File) {
    setPhoto(file);
    setPhotoPreview(URL.createObjectURL(file));
  }

  function handleCaseChange(value: string) {
    if (value === '__new__') {
      setShowNewCase(true);
    } else {
      setCaseId(value);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  if (styles.isLoading || sizes.isLoading || conditions.isLoading) return <LoadingSpinner />;

  return (
    <>
      <h1 className="mb-3">Add Hat</h1>

      <form onSubmit={handleSubmit}>
        <div className="card mb-3">
          <div className="card-body">
            <h6 className="card-title text-secondary mb-3">Photo</h6>
            <PhotoCapture onCapture={handlePhotoCapture} previewUrl={photoPreview} />
          </div>
        </div>

        <div className="card mb-3">
          <div className="card-body">
            <h6 className="card-title text-secondary mb-3">Details</h6>

            <div className="mb-3">
              <label className="form-label">Style</label>
              <select className="form-select" value={style} onChange={e => setStyle(e.target.value)}>
                {styles.data?.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>

            <div className="mb-3">
              <label className="form-label">Size</label>
              <select className="form-select" value={size} onChange={e => setSize(e.target.value)}>
                {sizes.data?.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>

            <div className="mb-3">
              <label className="form-label">Condition</label>
              <select className="form-select" value={condition} onChange={e => setCondition(e.target.value)}>
                {conditions.data?.map(c => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </div>

            <div className="mb-3">
              <label className="form-label">Assign to Case (optional)</label>
              <select className="form-select" value={caseId} onChange={e => handleCaseChange(e.target.value)}>
                <option value="">Unassigned</option>
                <option value="__new__">+ Create New Case...</option>
                {cases.data?.map(c => (
                  <option key={c.id} value={c.id}>
                    {c.display_id} ({c.case_type === 'archive' ? 'Archive' : 'Daily'} &middot; {c.hat_count} hats &middot; {c.room_name})
                  </option>
                ))}
              </select>
            </div>

            <div className="mb-3">
              <label className="form-label">Date Last Worn (optional)</label>
              <input type="date" className="form-control" value={dateLastWorn} onChange={e => setDateLastWorn(e.target.value)} />
            </div>
          </div>
        </div>

        {mutation.error && (
          <div className="alert alert-danger">{String(mutation.error)}</div>
        )}

        <button
          type="submit"
          className="btn btn-primary w-100 btn-lg"
          disabled={mutation.isPending}
        >
          {mutation.isPending ? 'Saving...' : 'Save Hat'}
        </button>
      </form>

      <NewCaseModal
        show={showNewCase}
        onClose={() => setShowNewCase(false)}
        onCreated={(id) => setCaseId(String(id))}
      />
    </>
  );
}
