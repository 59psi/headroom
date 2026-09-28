import { isNotFound } from '../api/client';
import { ErrorNote, describeError } from '../components/common/ErrorNote';
import { useState, useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, Link } from 'react-router';
import {
  getHat, updateHat, uploadHatPhoto, assignHat, updateHatColors, getColorwayOptions,
} from '../api/hats';
import { NewCaseModal } from '../components/common/NewCaseModal';
import { Combobox } from '../components/common/Combobox';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { useToast } from '../components/ui/Toast';
import { useDebouncedValue } from '../lib/useDebouncedValue';
import {
  useHatFormOptions, useHatPhoto, PhotoCard, HatBasicsCard, HatFormSkeleton, HatFormActions,
  type HatBasics,
} from '../components/hats/HatFormFields';
import type { ColorTag } from '../types';
import { invalidateHatViews, invalidateHatVocabulary } from '../lib/invalidate';
import { COLOR_TIERS, asTier, tierForRank } from '../lib/colorTiers';
import { uploadUrl } from '../lib/photo';
import { hatName } from '../lib/placement';
import { qk } from '../lib/queryKeys';

type ColorRow = ColorTag & { rowKey: number };

/**
 * A color row with a key of its own. Keyed by index, deleting color 2 of 3
 * handed color 3's data to color 2's inputs — correct on screen, but the
 * focused field and its native color picker stayed on the row that had just
 * changed meaning. Only uniqueness matters, so one counter for the module
 * does; outside the component, it is not a dependency of anything.
 */
let nextRowKey = 0;
function withKey(c: ColorTag): ColorRow {
  return { ...c, rowKey: nextRowKey++ };
}

/** The palette as the server would store it — for "did the form change it?". */
function paletteKey(colors: readonly ColorTag[]): string {
  return JSON.stringify(colors.map(c => [
    c.color_name.trim(), c.general_color.trim(), c.hex_value.toLowerCase(), c.tier,
  ]));
}

/**
 * A save that failed part-way: some writes landed, one did not, the rest
 * were not attempted.
 *
 * The form saves in up to four requests, and "Not saved" after the first one
 * had committed was false — the brand WAS saved, the hat page and the lists
 * just did not know yet, because nothing was invalidated on a failure. This
 * names what did land, so the retry is understood as finishing the save
 * rather than redoing it.
 */
class PartialSaveError extends Error {
  constructor(saved: string[], failed: string, cause: unknown) {
    const done = saved.length > 1
      ? `${saved.slice(0, -1).join(', ')} and ${saved[saved.length - 1]}`
      : saved[0];
    super(`${done.charAt(0).toUpperCase()}${done.slice(1)} saved; ${failed} not saved: ${describeError(cause)}`);
    this.name = 'PartialSaveError';
  }
}

export function EditHatPage() {
  const { hatId } = useParams<{ hatId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const id = Number(hatId);

  const hat = useQuery({ queryKey: qk.hat(id), queryFn: () => getHat(id), enabled: !isNaN(id) });
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
  // Each row carries a local key that survives removal of the row above it
  // (`withKey`).
  const [colors, setColors] = useState<ColorRow[]>([]);
  const [showNewCase, setShowNewCase] = useState(false);

  const modelOptions = useQuery({
    queryKey: qk.meta.colorwayModels(),
    queryFn: () => getColorwayOptions(),
  });
  // Scoped to the model, so it has to follow the model box — but only once
  // the typing has stopped, not on every keystroke (see `useDebouncedValue`).
  const settledModel = useDebouncedValue(modelName.trim());
  const colorwayOptions = useQuery({
    queryKey: qk.meta.colorwaysFor(settledModel),
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
  // The palette as seeded, by the same reasoning. Saving colors is itself a
  // decision now: `PUT /colors` marks the palette as the OWNER's, and a
  // re-analysis leaves an owner palette alone. Sending the seeded rows back
  // on every save claimed the analyzer's colors as yours the first time you
  // corrected a brand — and, when an analysis landed mid-edit, wrote the
  // stale seed over the fresh colors. Only a palette you changed is sent.
  const seededPalette = useRef('');
  // The last-worn date as seeded, for the same "did you change it?" test. A
  // wear is logged from the hat page, a tag or the Shortcut — any of which can
  // land while this form is open — and sending the seeded date back on every
  // save wrote over the wear that had just been logged.
  const seededLastWorn = useRef('');
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
        setPhotoPreview(uploadUrl(hat.data.photo_path));
      }
      setColors(hat.data.colors.map(withKey));
      seededPalette.current = paletteKey(hat.data.colors);
      seededLastWorn.current = hat.data.date_last_worn || '';
    }
  }, [hat.data, setPhotoPreview]);

  const mutation = useMutation({
    mutationFn: async () => {
      const data: Record<string, unknown> = {
        style: basics.style, size: basics.size, condition: basics.condition,
        // Empty means "not stated" -> null, so clearing the field clears the
        // value rather than storing an empty string that reads as an answer.
        construction: basics.construction.trim() || null,
      };
      // Sent only when the box differs from the date it was seeded with — and
      // then as null when it was emptied. The update applies only the keys it
      // is given, so leaving the key OUT means "keep it": clearing the date
      // used to be silently not saved, because an empty box sent no key; and
      // sending the untouched seed on every save overwrote a wear logged
      // elsewhere while the form was open (`seededLastWorn`).
      if (basics.dateLastWorn !== seededLastWorn.current) {
        data.date_last_worn = basics.dateLastWorn || null;
      }
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

      // Placement goes through `assign`, not the PUT: it is the one path that
      // validates capacity and keeps case and room mutually exclusive.
      const newCaseId = basics.caseId ? Number(basics.caseId) : null;
      // A case wins over a room, and no room means null — spelled out rather
      // than as a precedence-dependent double negative.
      const inACase = Boolean(basics.caseId);
      const newRoomId = !inACase && basics.roomId ? Number(basics.roomId) : null;
      // Against the LIVE row, unlike the prices: a retry after a partial save
      // must see the placement that already landed and skip it.
      const oldCaseId = hat.data?.case_id ?? null;
      const oldRoomId = hat.data?.direct_room_id ?? null;
      const palette = colors.map(({ rowKey: _key, ...c }) => c);

      // In this order on purpose. The PUT and the placement are the edits
      // this form is mostly for; the palette is sent only when changed; the
      // photo goes LAST because it is the one write whose repeat is not free
      // — each upload replaces the cutout and queues a new analysis — so it
      // runs only once everything before it has landed, and a retry after
      // ITS failure repeats only writes that are safe to repeat.
      const steps: Array<{ name: string; run: () => Promise<unknown> }> = [
        { name: 'details', run: () => updateHat(id, data) },
      ];
      if (newCaseId !== oldCaseId || newRoomId !== oldRoomId) {
        steps.push({ name: 'placement', run: () => assignHat(id, newCaseId, newRoomId) });
      }
      if (paletteKey(palette) !== seededPalette.current) {
        steps.push({ name: 'colors', run: () => updateHatColors(id, palette) });
      }
      if (photo) {
        steps.push({ name: 'photo', run: () => uploadHatPhoto(id, photo) });
      }

      const saved: string[] = [];
      for (const step of steps) {
        try {
          await step.run();
        } catch (err) {
          if (saved.length === 0) throw err;
          throw new PartialSaveError(saved, step.name, err);
        }
        saved.push(step.name);
      }
    },
    onSuccess: () => {
      // The toast lives at the app root, so it is still up on the hat page
      // this lands on — the acknowledgment arrives where the eye goes next.
      toast.success('Changes saved');
      navigate(`/hats/${id}`);
    },
    // Settled, not success: a save that failed part-way still changed the
    // hat, and the hat page and the lists must show what DID land.
    onSettled: () => {
      void invalidateHatViews(qc, id);
      // A resale price typed here stamps the hat `manual`, which takes it out
      // of the shared-price report, and a colorway flips its
      // `missing_colorway` — so that report (`shared_price_audit`) is stale
      // the moment this saves. `['admin', 'shared-prices']` is a sibling key
      // that nothing above covers; TanStack matches by prefix, and it
      // prefixes none of them.
      void qc.invalidateQueries({ queryKey: qk.admin.sharedPrices() });
      invalidateHatVocabulary(qc);
    },
  });

  function setBasic<K extends keyof HatBasics>(key: K, value: HatBasics[K]) {
    setBasics(prev => ({ ...prev, [key]: value }));
  }

  function setColor(i: number, change: Partial<ColorTag>) {
    setColors(prev => prev.map((c, j) => (j === i ? { ...c, ...change } : c)));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  // Back to the hat without saving — named by its id, as Edit case names its
  // case. Present from the first paint, labeled plain "Hat" for the moment a
  // cold load has no id to show yet: arriving with the hat instead would push
  // the title down just as the form replaced its skeleton.
  const backToHat = Number.isNaN(id) ? undefined : {
    to: `/hats/${id}`,
    label: hat.data ? hatName(hat.data) : 'Hat',
    title: 'Back to this hat without saving',
  };

  // The title stays up while the hat and the option lists load, so the page
  // does not blink from a spinner to a form.
  if (hat.isLoading || options.isLoading) {
    return (
      <>
        <PageHeader back={backToHat} title="Edit hat" />
        <HatFormSkeleton />
      </>
    );
  }
  if (hat.error && !isNotFound(hat.error)) {
    return (
      <>
        <PageHeader back={backToHat} title="Edit hat" />
        <div className="py-4">
          <ErrorNote of={hat} what="Could not load this hat" />
          <Link to={`/hats/${id}`} className="btn btn-outline-secondary mt-3">← Back to the hat</Link>
        </div>
      </>
    );
  }
  if (!hat.data) {
    return (
      <div className="text-center py-5">
        <h1 className="hr-empty-title">Hat not found</h1>
        <p className="text-secondary small mb-3">This hat may have been deleted or doesn't exist.</p>
        <Link to="/hats" className="btn btn-outline-secondary">← Back to hats</Link>
      </div>
    );
  }

  return (
    <>
      <PageHeader back={backToHat} title="Edit hat" />

      <form onSubmit={handleSubmit}>
        <PhotoCard onCapture={onCapture} previewUrl={photoPreview} />

        <HatBasicsCard
          values={basics}
          onChange={setBasic}
          options={options}
          onCreateCase={() => setShowNewCase(true)}
        />

        <Panel
          title="Identity and pricing"
          description="Override anything the analysis got wrong. A blank field is cleared."
        >
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
              label="Model name"
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
              <input id="hat-est-new" ref={estimatedRef} type="number" inputMode="decimal" step="0.01" className="form-control" value={estimatedPrice} onChange={e => setEstimatedPrice(e.target.value)} />
            </div>
            <div className="col-6">
              <label className="form-label" htmlFor="hat-resale">Resale ($)</label>
              <input id="hat-resale" ref={resaleRef} type="number" inputMode="decimal" step="0.01" className="form-control" value={resalePrice} onChange={e => setResalePrice(e.target.value)} />
            </div>
            {/* Full width under the pair, not squeezed into the resale
                column: at phone width a 170px column turned this into a
                ten-line ribbon beside an empty one. It is the one sentence on
                the form whose consequence is permanent, so it gets to be
                readable. */}
            <div className="col-12">
              <div className="form-text">
                Setting a resale price marks it as your own: it's used as-is
                and a re-analysis won't overwrite it. Clear it to hand the hat
                back to the live market feed.
              </div>
            </div>
          </div>

          <div>
            <label className="form-label" htmlFor="hat-design-notes">Design notes</label>
            <textarea
              id="hat-design-notes"
              className="form-control"
              rows={3}
              value={designNotes}
              onChange={e => setDesignNotes(e.target.value)}
            />
          </div>
        </Panel>

        <Panel
          title="Colors"
          description="Your edits stick — re-analysis keeps a palette you changed. Remove every color to hand them back to analysis."
          footer={(
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={() => setColors([
                ...colors,
                // A blank name is sent blank: the server names it after the
                // palette color of its hex, a real name rather than a
                // stand-in. The tier starts where its place in the list puts
                // it, and the picker on the row can change it.
                withKey({
                  color_name: '', general_color: '', hex_value: '#000000',
                  dominance_rank: colors.length + 1, tier: tierForRank(colors.length + 1),
                }),
              ])}
            >+ Add color</button>
          )}
        >
          {colors.length === 0 ? (
            <p className="text-muted small mb-0">No colors. Add one below, or reanalyze the hat to rebuild the palette.</p>
          ) : colors.map((color, i) => (
            // Swatch, name, tier and remove; the general color and tier under
            // the name on a phone and beside it where there is room — the old
            // flex-wrap put each input wherever it happened to fall.
            <div key={color.rowKey} className="hr-color-edit-row">
              <input
                type="color"
                aria-label={`Color ${i + 1} swatch`}
                className="form-control form-control-color hr-color-edit-swatch"
                value={color.hex_value}
                onChange={e => setColor(i, { hex_value: e.target.value })}
              />
              <input
                type="text"
                className="form-control hr-color-edit-name"
                placeholder="Color name"
                aria-label={`Color ${i + 1} name`}
                maxLength={50}
                value={color.color_name}
                onChange={e => setColor(i, { color_name: e.target.value })}
              />
              <input
                type="text"
                className="form-control hr-color-edit-general"
                placeholder="General"
                aria-label={`Color ${i + 1} general color`}
                maxLength={30}
                value={color.general_color}
                onChange={e => setColor(i, { general_color: e.target.value })}
              />
              <select
                className="form-select hr-color-edit-tier"
                aria-label={`Color ${i + 1} tier`}
                value={color.tier ?? 'primary'}
                onChange={e => setColor(i, { tier: asTier(e.target.value) })}
              >
                {COLOR_TIERS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
              <button
                type="button"
                className="btn btn-outline-danger btn-sm hr-color-edit-remove"
                aria-label={`Remove color ${i + 1}`}
                onClick={() => {
                  const updated = colors.filter((_, j) => j !== i)
                    .map((c, j) => ({ ...c, dominance_rank: j + 1 }));
                  setColors(updated);
                }}
              >×</button>
            </div>
          ))}
        </Panel>

        <HatFormActions
          error={
            <ErrorNote
              of={mutation}
              what={mutation.error instanceof PartialSaveError ? 'Partly saved' : 'Not saved'}
              className="mb-2"
            />
          }
        >
          <Link to={`/hats/${id}`} className="btn btn-outline-secondary">Cancel</Link>
          <button
            type="submit"
            className="btn btn-primary hr-form-actions-main"
            disabled={mutation.isPending}
          >
            {mutation.isPending ? 'Saving…' : 'Save changes'}
          </button>
        </HatFormActions>
      </form>

      <NewCaseModal
        show={showNewCase}
        onClose={() => setShowNewCase(false)}
        onCreated={(newCaseId) => setBasic('caseId', String(newCaseId))}
      />
    </>
  );
}
