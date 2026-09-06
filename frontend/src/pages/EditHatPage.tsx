import { isNotFound } from '../api/client';
import { ErrorNote } from '../components/common/ErrorNote';
import { useState, useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router';
import {
  getHat, updateHat, uploadHatPhoto, assignHat, updateHatColors, getColorwayOptions,
} from '../api/hats';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { NewCaseModal } from '../components/common/NewCaseModal';
import { Combobox } from '../components/common/Combobox';
import { useDebouncedValue } from '../lib/useDebouncedValue';
import {
  useHatFormOptions, useHatPhoto, PhotoCard, HatBasicsCard, type HatBasics,
} from '../components/hats/HatFormFields';
import type { ColorTag } from '../types';

type ColorRow = ColorTag & { rowKey: number };
import { invalidateHatViews, invalidateHatVocabulary } from '../lib/invalidate';

export function EditHatPage() {
  const { hatId } = useParams<{ hatId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const id = Number(hatId);

  const hat = useQuery({ queryKey: ['hat', id], queryFn: () => getHat(id), enabled: !isNaN(id) });
  const options = useHatFormOptions();

  const [basics, setBasics] = useState<HatBasics>({
    style: '', size: '', condition: '', construction: '', artistSeries: '',
    caseId: '', roomId: '', limitedEdition: false,
    dateLastWorn: '', purchasePrice: '', purchasedAt: '',
  });
  const [brand, setBrand] = useState('');
  const [modelName, setModelName] = useState('');
  const [colorway, setColorway] = useState('');
  const [estimatedPrice, setEstimatedPrice] = useState('');
  const [resalePrice, setResalePrice] = useState('');
  const [designNotes, setDesignNotes] = useState('');
  const { photo, photoPreview, setPhotoPreview, onCapture } = useHatPhoto();
  // Each row carries a local key that survives removal of the row above it.
  // Keyed by index, deleting color 2 of 3 handed color 3's data to color 2's
  // inputs — correct on screen, but the focused field and its native color
  // picker stayed on the row that had just changed meaning.
  const [colors, setColors] = useState<ColorRow[]>([]);
  const nextRowKey = useRef(0);
  const withKey = (c: ColorTag): ColorRow => ({ ...c, rowKey: nextRowKey.current++ });
  const [showNewCase, setShowNewCase] = useState(false);

  const modelOptions = useQuery({
    queryKey: ['meta', 'colorways', 'models'],
    queryFn: () => getColorwayOptions(),
  });
  // Scoped to the model, so it has to follow the model box — but only once
  // the typing has stopped, not on every keystroke (see `useDebouncedValue`).
  const settledModel = useDebouncedValue(modelName.trim());
  const colorwayOptions = useQuery({
    queryKey: ['meta', 'colorways', settledModel],
    queryFn: () => getColorwayOptions(settledModel),
    enabled: settledModel.length > 1,
  });

  // Seed the form once per hat, not on every refetch. Since 2.6.0 analysis runs
  // in the background, so this row changes *while you are editing it* — when the
  // worker finished, the next refetch re-ran this effect and every field you had
  // typed reverted to the server's values mid-sentence.
  const seededFor = useRef<number | null>(null);

  // The prices AS SEEDED, and the price inputs themselves.
  //
  // The seeded values, not `hat.data`, are what "did the user change this?"
  // must be measured against. Seeding is frozen per hat (above) while
  // `hat.data` keeps refetching (`refetchOnWindowFocus`), so comparing the box
  // to the live row reopens the bug the comparison exists to close: tab away
  // from a hat whose resale is a scraped median, let a re-analysis land a
  // fresher number, come back and save anything at all — the box still holds
  // the OLD value, it now differs from the row, and it gets written and
  // stamped `manual` forever.
  //
  // The refs are for `validity.badInput`. A `type="number"` input reports
  // `value === ""` both when you clear it and when it rejects what you typed
  // ("1e"), which are opposite intentions flattened into one string — and this
  // form treats an empty box as "clear this price".
  const seededPrices = useRef<{ estimated: number | null; resale: number | null }>({
    estimated: null, resale: null,
  });
  const estimatedRef = useRef<HTMLInputElement>(null);
  const resaleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (hat.data && seededFor.current !== hat.data.id) {
      seededFor.current = hat.data.id;
      setBasics({
        style: hat.data.style,
        size: hat.data.size,
        condition: hat.data.condition,
        construction: hat.data.construction || '',
        artistSeries: hat.data.artist_series || '',
        caseId: hat.data.case_id?.toString() || '',
        // The DIRECT room only — a cased hat's `room_id` comes from its case,
        // and seeding that here would show a room the form cannot own and
        // would then try to save alongside the case.
        roomId: hat.data.direct_room_id?.toString() || '',
        limitedEdition: hat.data.limited_edition,
        dateLastWorn: hat.data.date_last_worn || '',
        purchasePrice: hat.data.purchase_price != null ? String(hat.data.purchase_price) : '',
        // `<input type="date">` only accepts YYYY-MM-DD; the API sends a full
        // ISO timestamp, which the control silently rejects and renders blank.
        purchasedAt: hat.data.purchased_at ? hat.data.purchased_at.slice(0, 10) : '',
      });
      setBrand(hat.data.brand || '');
      setModelName(hat.data.model_name || '');
      setColorway(hat.data.colorway || '');
      setEstimatedPrice(hat.data.estimated_new_price != null ? String(hat.data.estimated_new_price) : '');
      setResalePrice(hat.data.resale_price != null ? String(hat.data.resale_price) : '');
      seededPrices.current = {
        estimated: hat.data.estimated_new_price ?? null,
        resale: hat.data.resale_price ?? null,
      };
      setDesignNotes(hat.data.design_notes || '');
      if (hat.data.photo_path) {
        setPhotoPreview(`/uploads/${hat.data.photo_path}`);
      }
      setColors(hat.data.colors.map(withKey));
    }
  }, [hat.data]);

  const mutation = useMutation({
    mutationFn: async () => {
      const data: Record<string, unknown> = {
        style: basics.style, size: basics.size, condition: basics.condition,
        // Empty means "not stated" -> null, so clearing the field clears the
        // value rather than storing an empty string that reads as an answer.
        construction: basics.construction.trim() || null,
      };
      if (basics.dateLastWorn) data.date_last_worn = basics.dateLastWorn;
      data.brand = brand || null;
      data.model_name = modelName || null;
      data.artist_series = basics.artistSeries.trim() || null;
      data.colorway = colorway || null;
      data.purchase_price = basics.purchasePrice ? Number(basics.purchasePrice) : null;
      data.purchased_at = basics.purchasedAt ? `${basics.purchasedAt}T00:00:00` : null;
      data.design_notes = designNotes || null;
      // These two are the only fields whose mere PRESENCE in the payload is
      // itself a decision. `hat_service.update_hat` reads a sent key as "a
      // person typed this number" and stamps the price `manual` — which is
      // permanent: `resolve_retail` returns it forever, and both
      // `refresh_melin_resale` and `_apply_resale_pointer` bail on it.
      //
      // This form seeds both boxes from the loaded hat, so sending them
      // unconditionally meant editing a colorway relabeled a scraped
      // melinrecap median as "Price you entered — used as given" and froze it
      // against every future analysis. Same number on screen, different
      // meaning, no way to tell. Sent only when actually changed.
      // Compared against the SEEDED value and guarded on `badInput` — see the
      // note on `seededPrices`. Returns null for "leave this key out".
      const priceToSend = (
        typed: string,
        seeded: number | null,
        input: HTMLInputElement | null,
      ): { send: boolean; value: number | null } => {
        // Unparseable text in the box reads as `value === ""`, which is
        // indistinguishable from cleared. Sending null there would wipe a
        // real price because of a typo the browser already rejected.
        if (input?.validity.badInput) return { send: false, value: null };
        const value = typed ? Number(typed) : null;
        return { send: value !== seeded, value };
      };

      const est = priceToSend(estimatedPrice, seededPrices.current.estimated, estimatedRef.current);
      if (est.send) data.estimated_new_price = est.value;
      const resale = priceToSend(resalePrice, seededPrices.current.resale, resaleRef.current);
      if (resale.send) data.resale_price = resale.value;
      data.limited_edition = basics.limitedEdition;

      await updateHat(id, data);

      // Placement goes through `assign`, not the PUT: it is the one path that
      // validates capacity and keeps case and room mutually exclusive.
      const newCaseId = basics.caseId ? Number(basics.caseId) : null;
      // A case wins over a room, and no room means null — spelled out rather
      // than as a precedence-dependent double negative.
      const inACase = Boolean(basics.caseId);
      const newRoomId = !inACase && basics.roomId ? Number(basics.roomId) : null;
      const oldCaseId = hat.data?.case_id ?? null;
      const oldRoomId = hat.data?.direct_room_id ?? null;
      if (newCaseId !== oldCaseId || newRoomId !== oldRoomId) {
        await assignHat(id, newCaseId, newRoomId);
      }

      if (photo) {
        await uploadHatPhoto(id, photo);
      }

      await updateHatColors(id, colors.map(({ rowKey: _key, ...c }) => c));
    },
    onSuccess: () => {
      invalidateHatViews(qc, id);
      // A resale price typed here stamps the hat `manual`, which removes it
      // from the shared-price report, and a colorway flips `missing_colorway`
      // — so that report is stale the moment this saves. A SIBLING key, not
      // covered by anything above (CLAUDE.md, `shared_price_audit`).
      qc.invalidateQueries({ queryKey: ['admin', 'shared-prices'] });
      invalidateHatVocabulary(qc);
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
  if (hat.error && !isNotFound(hat.error)) {
    return <div className="py-4"><ErrorNote of={{ isError: true, error: hat.error }} what="Could not load this hat" /></div>;
  }
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
              <label className="form-label" htmlFor="hat-brand">Brand</label>
              <input id="hat-brand" type="text" className="form-control" value={brand} onChange={e => setBrand(e.target.value)} placeholder="e.g. Melin" />
            </div>

            {/* A Combobox, not a <datalist>: iOS renders a datalist as a thin
                strip above the keyboard that is easy to miss entirely, so 188
                harvested colorways read as a blank text box. Same component
                the Basics card uses for construction and collection. */}
            <div className="mb-3">
              <Combobox
                id="hat-model-name"
                label="Model Name"
                value={modelName}
                onChange={setModelName}
                options={(modelOptions.data ?? []).map(o => o.value)}
                placeholder="e.g. A-Game Hydro"
              />
            </div>

            {/* Collection / collab lives in the Basics card, beside
                construction — both answer "what is this hat", and it has to be
                on the Add form too, which has no Identity card. One definition
                in `HatFormFields`, rendered by both pages. */}

            <div className="mb-3">
              <Combobox
                id="hat-colorway"
                label="Colorway"
                value={colorway}
                onChange={setColorway}
                options={(colorwayOptions.data ?? []).map(o => o.value)}
                placeholder="e.g. Heather Ocean"
                help={<>Suggestions come from the Melin Recap catalog for this model (refresh it under Settings &rarr; Data).</>}
              />
            </div>

            {/* Price paid moved up into HatBasicsCard, where the Add form has
                it too — two inputs for one column is how they end up
                disagreeing about which was edited last. */}
            <div className="row g-2 mb-3">
              <div className="col-6">
                <label className="form-label" htmlFor="hat-est-new">Est. new retail ($)</label>
                <input id="hat-est-new" ref={estimatedRef} type="number" step="0.01" className="form-control" value={estimatedPrice} onChange={e => setEstimatedPrice(e.target.value)} />
              </div>
              <div className="col-6">
                <label className="form-label" htmlFor="hat-resale">Resale ($)</label>
                <input id="hat-resale" ref={resaleRef} type="number" step="0.01" className="form-control" value={resalePrice} onChange={e => setResalePrice(e.target.value)} />
                <div className="form-text small">
                  Setting this marks it as your own price: it's used as-is and
                  a re-analysis won't overwrite it. Clear it to hand the hat
                  back to the live market feed.
                </div>
              </div>
            </div>

            <div className="mb-3">
              <label className="form-label">Design Notes</label>
              <textarea
                aria-label="Design Notes"
                className="form-control"
                rows={3}
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
              <div key={color.rowKey} className="mb-2">
                <div className="d-flex align-items-center gap-2 flex-wrap">
                  <input
                    type="color"
                    aria-label={`Color ${i + 1} swatch`}
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
                    aria-label={`Color ${i + 1} name`}
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
                    aria-label={`Color ${i + 1} general color`}
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
                    aria-label={`Remove color ${i + 1}`}
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
                withKey({ color_name: '', general_color: '', hex_value: '#000000', dominance_rank: colors.length + 1, tier: 'primary' }),
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
