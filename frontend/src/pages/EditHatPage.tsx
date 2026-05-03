import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getHat, updateHat, uploadHatPhoto, assignHat, updateHatColors,
  getStyles, getSizes, getConditions,
} from '../api/hats';
import { listCases } from '../api/cases';
import { PhotoCapture } from '../components/photos/PhotoCapture';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { NewCaseModal } from '../components/common/NewCaseModal';
import type { ColorTag } from '../types';

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
  const [brand, setBrand] = useState('');
  const [modelName, setModelName] = useState('');
  const [estimatedPrice, setEstimatedPrice] = useState('');
  const [resalePrice, setResalePrice] = useState('');
  const [designNotes, setDesignNotes] = useState('');
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [colors, setColors] = useState<ColorTag[]>([]);
  const [showNewCase, setShowNewCase] = useState(false);

  useEffect(() => {
    if (hat.data) {
      setStyle(hat.data.style);
      setSize(hat.data.size);
      setCondition(hat.data.condition);
      setDateLastWorn(hat.data.date_last_worn || '');
      setCaseId(hat.data.case_id?.toString() || '');
      setBrand(hat.data.brand || '');
      setModelName(hat.data.model_name || '');
      setEstimatedPrice(hat.data.estimated_new_price != null ? String(hat.data.estimated_new_price) : '');
      setResalePrice(hat.data.resale_price != null ? String(hat.data.resale_price) : '');
      setDesignNotes(hat.data.design_notes || '');
      if (hat.data.photo_path) {
        setPhotoPreview(`/uploads/${hat.data.photo_path}`);
      }
      setColors(hat.data.colors.map(c => ({ ...c })));
    }
  }, [hat.data]);

  const mutation = useMutation({
    mutationFn: async () => {
      const data: Record<string, unknown> = { style, size, condition };
      if (dateLastWorn) data.date_last_worn = dateLastWorn;
      data.brand = brand || null;
      data.model_name = modelName || null;
      data.design_notes = designNotes || null;
      data.estimated_new_price = estimatedPrice ? Number(estimatedPrice) : null;
      data.resale_price = resalePrice ? Number(resalePrice) : null;

      await updateHat(id, data);

      const newCaseId = caseId ? Number(caseId) : null;
      const oldCaseId = hat.data?.case_id ?? null;
      if (newCaseId !== oldCaseId) {
        await assignHat(id, newCaseId);
      }

      if (photo) {
        await uploadHatPhoto(id, photo);
      }

      await updateHatColors(id, colors);
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

  function handleCaseChange(value: string) {
    if (value === '__new__') setShowNewCase(true);
    else setCaseId(value);
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
            <div className="card-title">Photo</div>
            <PhotoCapture onCapture={handlePhotoCapture} previewUrl={photoPreview} />
          </div>
        </div>

        <div className="card mb-3">
          <div className="card-body">
            <div className="card-title">Details</div>

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
              <select className="form-select" value={caseId} onChange={e => handleCaseChange(e.target.value)}>
                <option value="">Unassigned</option>
                <option value="__new__">+ Create New Case…</option>
                {cases.data?.map(c => (
                  <option key={c.id} value={c.id}>
                    {c.display_id} ({c.case_type === 'archive' ? 'Archive' : 'Daily'} · {c.hat_count} hats · {c.room_name})
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

        <div className="card mb-3">
          <div className="card-body">
            <div className="card-title">AI / Pricing Overrides</div>
            <p className="text-secondary small mb-3">
              Override anything Claude got wrong. Blank = leave as null.
            </p>

            <div className="mb-3">
              <label className="form-label">Brand</label>
              <input type="text" className="form-control" value={brand} onChange={e => setBrand(e.target.value)} placeholder="e.g. Melin" />
            </div>

            <div className="mb-3">
              <label className="form-label">Model Name</label>
              <input type="text" className="form-control" value={modelName} onChange={e => setModelName(e.target.value)} placeholder="e.g. A-Game Hydro" />
            </div>

            <div className="row g-2 mb-3">
              <div className="col-6">
                <label className="form-label">Est. New ($)</label>
                <input type="number" step="0.01" className="form-control" value={estimatedPrice} onChange={e => setEstimatedPrice(e.target.value)} />
              </div>
              <div className="col-6">
                <label className="form-label">Resale ($)</label>
                <input type="number" step="0.01" className="form-control" value={resalePrice} onChange={e => setResalePrice(e.target.value)} />
              </div>
            </div>

            <div className="mb-3">
              <label className="form-label">Design Notes</label>
              <textarea
                className="form-control"
                rows={2}
                value={designNotes}
                onChange={e => setDesignNotes(e.target.value)}
              />
            </div>
          </div>
        </div>

        <div className="card mb-3">
          <div className="card-body">
            <div className="card-title">Colors</div>

            {colors.map((color, i) => (
              <div key={i} className="mb-2">
                <div className="d-flex align-items-center gap-2 flex-wrap">
                  <input
                    type="color"
                    className="form-control form-control-color"
                    value={color.hex_value}
                    onChange={e => {
                      const updated = [...colors];
                      updated[i] = { ...updated[i], hex_value: e.target.value };
                      setColors(updated);
                    }}
                  />
                  <input
                    type="text"
                    className="form-control flex-grow-1"
                    style={{ minWidth: 120 }}
                    placeholder="Color name"
                    value={color.color_name}
                    onChange={e => {
                      const updated = [...colors];
                      updated[i] = { ...updated[i], color_name: e.target.value };
                      setColors(updated);
                    }}
                  />
                  <input
                    type="text"
                    className="form-control flex-grow-1"
                    style={{ minWidth: 120 }}
                    placeholder="General"
                    value={color.general_color}
                    onChange={e => {
                      const updated = [...colors];
                      updated[i] = { ...updated[i], general_color: e.target.value };
                      setColors(updated);
                    }}
                  />
                  <button
                    type="button"
                    className="btn btn-outline-danger btn-sm"
                    onClick={() => {
                      const updated = colors.filter((_, j) => j !== i)
                        .map((c, j) => ({ ...c, dominance_rank: j + 1 }));
                      setColors(updated);
                    }}
                  >×</button>
                </div>
              </div>
            ))}

            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={() => setColors([
                ...colors,
                { color_name: '', general_color: '', hex_value: '#000000', dominance_rank: colors.length + 1, tier: 'primary' },
              ])}
            >+ Add Color</button>
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
          {mutation.isPending ? 'Saving…' : 'Save Changes'}
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
