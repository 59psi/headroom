import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router';
import {
  getHat, updateHat, uploadHatPhoto, assignHat, updateHatColors,
} from '../api/hats';
import { apiFetch } from '../api/client';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { NewCaseModal } from '../components/common/NewCaseModal';
import {
  useHatFormOptions, useHatPhoto, PhotoCard, HatBasicsCard, type HatBasics,
} from '../components/hats/HatFormFields';
import type { ColorTag } from '../types';

export function EditHatPage() {
  const { hatId } = useParams<{ hatId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const id = Number(hatId);

  const hat = useQuery({ queryKey: ['hat', id], queryFn: () => getHat(id), enabled: !isNaN(id) });
  const options = useHatFormOptions();

  const [basics, setBasics] = useState<HatBasics>({
    style: '', size: '', condition: '', hydrolite: false, caseId: '', dateLastWorn: '',
  });
  const [brand, setBrand] = useState('');
  const [modelName, setModelName] = useState('');
  const [colorway, setColorway] = useState('');
  const [purchasePrice, setPurchasePrice] = useState('');
  const [estimatedPrice, setEstimatedPrice] = useState('');
  const [resalePrice, setResalePrice] = useState('');
  const [designNotes, setDesignNotes] = useState('');
  const { photo, photoPreview, setPhotoPreview, onCapture } = useHatPhoto();
  const [colors, setColors] = useState<ColorTag[]>([]);
  const [showNewCase, setShowNewCase] = useState(false);

  const modelOptions = useQuery({
    queryKey: ['meta', 'colorways', 'models'],
    queryFn: () => apiFetch<{ value: string }[]>('/api/meta/colorways'),
  });
  const colorwayOptions = useQuery({
    queryKey: ['meta', 'colorways', modelName],
    queryFn: () => apiFetch<{ value: string }[]>(`/api/meta/colorways?model=${encodeURIComponent(modelName)}`),
    enabled: modelName.length > 1,
  });

  useEffect(() => {
    if (hat.data) {
      setBasics({
        style: hat.data.style,
        size: hat.data.size,
        condition: hat.data.condition,
        hydrolite: hat.data.hydrolite,
        caseId: hat.data.case_id?.toString() || '',
        dateLastWorn: hat.data.date_last_worn || '',
      });
      setBrand(hat.data.brand || '');
      setModelName(hat.data.model_name || '');
      setColorway(hat.data.colorway || '');
      setPurchasePrice(hat.data.purchase_price != null ? String(hat.data.purchase_price) : '');
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
      const data: Record<string, unknown> = {
        style: basics.style, size: basics.size, condition: basics.condition,
        hydrolite: basics.hydrolite,
      };
      if (basics.dateLastWorn) data.date_last_worn = basics.dateLastWorn;
      data.brand = brand || null;
      data.model_name = modelName || null;
      data.colorway = colorway || null;
      data.purchase_price = purchasePrice ? Number(purchasePrice) : null;
      data.design_notes = designNotes || null;
      data.estimated_new_price = estimatedPrice ? Number(estimatedPrice) : null;
      data.resale_price = resalePrice ? Number(resalePrice) : null;

      await updateHat(id, data);

      const newCaseId = basics.caseId ? Number(basics.caseId) : null;
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

  function setBasic<K extends keyof HatBasics>(key: K, value: HatBasics[K]) {
    setBasics(prev => ({ ...prev, [key]: value }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  if (hat.isLoading || options.isLoading) return <LoadingSpinner />;
  if (!hat.data) return <div className="alert alert-danger">Hat not found</div>;

  return (
    <>
      <h1 className="mb-3">Edit Hat</h1>

      <form onSubmit={handleSubmit}>
        <PhotoCard onCapture={onCapture} previewUrl={photoPreview} />

        <HatBasicsCard
          values={basics}
          onChange={setBasic}
          options={options}
          onCreateCase={() => setShowNewCase(true)}
        />

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
              <input type="text" className="form-control" value={modelName} onChange={e => setModelName(e.target.value)} placeholder="e.g. A-Game Hydro" list="model-options" />
              <datalist id="model-options">
                {modelOptions.data?.map(o => <option key={o.value} value={o.value} />)}
              </datalist>
            </div>

            <div className="mb-3">
              <label className="form-label">Colorway</label>
              <input type="text" className="form-control" value={colorway} onChange={e => setColorway(e.target.value)} placeholder="e.g. Heather Ocean" list="colorway-options" />
              <datalist id="colorway-options">
                {colorwayOptions.data?.map(o => <option key={o.value} value={o.value} />)}
              </datalist>
              <div className="form-text small">Suggestions come from the Melin Recap catalog (refresh it in Settings)</div>
            </div>

            <div className="mb-3">
              <label className="form-label">Purchase price (what you paid)</label>
              <input type="number" step="0.01" className="form-control" value={purchasePrice} onChange={e => setPurchasePrice(e.target.value)} placeholder="Cost basis" />
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
        onCreated={(newCaseId) => setBasic('caseId', String(newCaseId))}
      />
    </>
  );
}
