import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import { getHat, updateHat, uploadHatPhoto, assignHat, getStyles, getSizes, getConditions } from '../api/hats';
import { listCases } from '../api/cases';
import { PhotoCapture } from '../components/photos/PhotoCapture';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

export function EditHatPage() {
  const { hatId } = useParams<{ hatId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const id = Number(hatId);

  const hat = useQuery({ queryKey: ['hat', id], queryFn: () => getHat(id), enabled: !isNaN(id) });
  const styles = useQuery({ queryKey: ['meta', 'styles'], queryFn: getStyles });
  const sizes = useQuery({ queryKey: ['meta', 'sizes'], queryFn: getSizes });
  const conditions = useQuery({ queryKey: ['meta', 'conditions'], queryFn: getConditions });
  const cases = useQuery({ queryKey: ['cases'], queryFn: listCases });

  const [style, setStyle] = useState('');
  const [size, setSize] = useState('');
  const [condition, setCondition] = useState('');
  const [dateLastWorn, setDateLastWorn] = useState('');
  const [caseId, setCaseId] = useState('');
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);

  useEffect(() => {
    if (hat.data) {
      setStyle(hat.data.style);
      setSize(hat.data.size);
      setCondition(hat.data.condition);
      setDateLastWorn(hat.data.date_last_worn || '');
      setCaseId(hat.data.case_id?.toString() || '');
      if (hat.data.photo_path) {
        setPhotoPreview(`/uploads/${hat.data.photo_path}`);
      }
    }
  }, [hat.data]);

  const mutation = useMutation({
    mutationFn: async () => {
      const data: Record<string, unknown> = { style, size, condition };
      if (dateLastWorn) data.date_last_worn = dateLastWorn;
      await updateHat(id, data);

      // Handle case reassignment
      const newCaseId = caseId ? Number(caseId) : null;
      const oldCaseId = hat.data?.case_id ?? null;
      if (newCaseId !== oldCaseId) {
        await assignHat(id, newCaseId);
      }

      // Handle photo change
      if (photo) {
        await uploadHatPhoto(id, photo);
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hat', id] });
      qc.invalidateQueries({ queryKey: ['hats'] });
      qc.invalidateQueries({ queryKey: ['cases'] });
      navigate(`/hats/${id}`);
    },
  });

  function handlePhotoCapture(file: File) {
    setPhoto(file);
    setPhotoPreview(URL.createObjectURL(file));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  if (hat.isLoading || styles.isLoading || sizes.isLoading || conditions.isLoading) return <LoadingSpinner />;
  if (!hat.data) return <div className="alert alert-danger">Hat not found</div>;

  return (
    <>
      <h1 className="mb-3">Edit Hat</h1>

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
              <label className="form-label">Case Assignment</label>
              <select className="form-select" value={caseId} onChange={e => setCaseId(e.target.value)}>
                <option value="">Unassigned</option>
                {cases.data?.map(c => (
                  <option key={c.id} value={c.id}>
                    {c.display_id} ({c.case_type === 'archive' ? 'Archive' : 'Daily'} &middot; {c.hat_count} hats)
                  </option>
                ))}
              </select>
            </div>

            <div className="mb-3">
              <label className="form-label">Date Last Worn</label>
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
          {mutation.isPending ? 'Saving...' : 'Save Changes'}
        </button>
      </form>
    </>
  );
}
