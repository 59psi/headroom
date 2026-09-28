import type { ReactNode } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, Link } from 'react-router';
import { getCase, deleteCase, updateCase } from '../api/cases';
import { listRooms } from '../api/rooms';
import { hatLabelsUrl } from '../api/settings';
import { tileSrc } from '../lib/photo';
import { CaseCollage } from '../components/cases/CaseCollage';
import { CaseFillMeter, caseFillLabel, caseTypeLabel } from '../components/cases/CaseTile';
import { invalidateHatViews } from '../lib/invalidate';
import { TagUrlRow } from '../components/common/TagUrlRow';
import { ErrorNote } from '../components/common/ErrorNote';
import { isNotFound } from '../api/client';
import { Panel } from '../components/ui/Panel';
import { StatusPill } from '../components/ui/StatusPill';
import { SaveState, mutationSaveStatus } from '../components/ui/SaveState';
import { useConfirm } from '../components/ui/Dialogs';
import { useToast } from '../components/ui/Toast';
import type { CaseDetail } from '../types';

export function CaseDetailPage() {
  const { displayId } = useParams<{ displayId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();

  const { data, isLoading, error } = useQuery({
    queryKey: ['case', displayId],
    queryFn: () => getCase(displayId!),
    enabled: !!displayId,
  });
  // For the in-place room picker. Same key and fetcher as both case forms, so
  // arriving here from one of them costs no request.
  const roomsQ = useQuery({ queryKey: ['rooms'], queryFn: listRooms, enabled: !!data });

  const removeMutation = useMutation({
    mutationFn: () => deleteCase(displayId!),
    // Deleting a case DETACHES every hat in it into the room the case stood in
    // (`case_service.delete_case`, since 2.57.1 — they used to be left in no
    // room at all). So this changes hats and that room's loose-hat list, not
    // just cases — `['hats']`, `['rooms']` and `['room']` were all left stale
    // by invalidating `['cases']` alone.
    onSuccess: () => {
      invalidateHatViews(qc);
      toast.success(`Case ${displayId} deleted`);
      navigate('/cases');
    },
  });

  // Moving a case to another room, in place. It used to be Edit → change
  // the room → Save → back, four steps for the one edit a case gets most
  // (the box went to another room). The server's answer is predictable — the
  // room we picked, under the name we already have — so the page shows it at
  // once and only a failure changes anything: the old room comes back, with
  // the reason under the picker.
  const moveMutation = useMutation({
    mutationFn: (roomId: number) => updateCase(displayId!, { room_id: roomId }),
    onMutate: async (roomId: number) => {
      await qc.cancelQueries({ queryKey: ['case', displayId] });
      const prev = qc.getQueryData<CaseDetail>(['case', displayId]);
      const name = roomsQ.data?.find(r => r.id === roomId)?.name;
      if (prev) {
        qc.setQueryData<CaseDetail>(['case', displayId], {
          ...prev, room_id: roomId, room_name: name ?? prev.room_name,
        });
      }
      return { prev };
    },
    onError: (_err, _roomId, ctx) => {
      if (ctx?.prev) qc.setQueryData(['case', displayId], ctx.prev);
    },
    // The case moved between rooms: both rooms' counts and contents change,
    // and every hat inside now reports a new `room_name` — the same reach as
    // the Edit form's save, which this replaces for the room field.
    onSettled: () => { void invalidateHatViews(qc); },
  });

  if (isLoading) return <CaseDetailSkeleton />;
  // Only a 404 is "not found". Every other failure — a locked database, a
  // dead server — used to render the same "may have been deleted" copy,
  // which told the reader the opposite of the truth.
  if (error && !isNotFound(error)) return (
    <div className="py-4">
      <ErrorNote of={{ isError: true, error }} what="Could not load this case" />
      <Link to="/cases" className="btn btn-outline-secondary mt-3">Back to cases</Link>
    </div>
  );
  if (!data) return (
    <div className="hr-cr-empty mt-3">
      <p className="hr-cr-empty-title">Case not found</p>
      <p className="hr-cr-empty-text">This case may have been deleted or doesn't exist.</p>
      <Link to="/cases" className="btn btn-outline-secondary">Back to cases</Link>
    </div>
  );

  // Served, never restated here. These were `data.capacity ?? 6` and
  // `?? 4` — a second copy of a rule `services/capacity.py` owns, and wrong
  // twice: 4 is the OVERFILL limit rather than nominal capacity, so a full
  // three-hat case displayed "3/4" and invited an add the API would accept
  // only as overfull; and the hardcoded 6 went stale the moment beanie
  // capacity moved. That figure has since been 3, then 8, then 6 again —
  // which is the whole argument for serving it rather than typing it.
  const maxBeanies = data.nominal_beanie;
  const maxRegular = data.nominal_regular;

  let capacityDisplay: ReactNode;
  if (data.hat_count === 0) {
    capacityDisplay = (
      <div className="hr-case-fill-empty">
        {data.capacity
          ? `Empty — holds ${data.capacity}`
          : `Empty — holds ${maxRegular} hats or ${maxBeanies} beanies`}
      </div>
    );
  } else if (data.beanie_count > 0) {
    capacityDisplay = (
      <div className="hr-case-fill">
        <span className="hr-case-fill-figure">{data.beanie_count}/{maxBeanies}</span>
        <span className="hr-case-fill-label">Beanies</span>
      </div>
    );
  } else {
    capacityDisplay = (
      <div className="hr-case-fill">
        <span className="hr-case-fill-figure">{data.regular_count}/{maxRegular}</span>
        <span className="hr-case-fill-label">Hats</span>
      </div>
    );
  }

  const fill = caseFillLabel(data);
  const hatCount = data.hat_count;
  // "Its 1 hat stays" / "Its 2 hats stay".
  const hatsStay = hatCount === 1 ? '1 hat stays' : `${hatCount} hats stay`;
  // Until the room list arrives the picker still has to SHOW the case's room,
  // so it starts with the one option it already knows. The same option stays
  // when the list arrives WITHOUT that room — a case orphaned by an older
  // version (`update_case` names this as the path that repairs one). With no
  // option matching its value the select would display the first room while
  // meaning none, and choosing that room fired no change: the one room the
  // case could not be moved to was the one it appeared to be in.
  const ownRoom = { id: data.room_id, name: data.room_name };
  const roomOptions = !roomsQ.data
    ? [ownRoom]
    : roomsQ.data.some(r => r.id === data.room_id)
      ? roomsQ.data
      : [ownRoom, ...roomsQ.data];

  const { display_id: caseId, room_name: roomName } = data;
  async function handleDelete() {
    const ok = await confirm({
      title: hatCount > 0 ? `Delete case ${caseId}?` : `Delete empty case ${caseId}?`,
      // Not "will become unassigned": since 2.57.1 the hats stay in the room
      // the case was in, as loose hats (`case_service.delete_case`). The old
      // warning described a loss that no longer happens.
      body: hatCount > 0
        ? `Its ${hatsStay} in ${roomName}, out of a case. This can’t be undone.`
        : undefined,
      confirmLabel: 'Delete case',
      tone: 'danger',
    });
    if (ok) removeMutation.mutate();
  }

  return (
    <>
      <header className="hr-cr-head">
        <div className="hr-cr-title">
          <Link to="/cases" className="hr-cr-back">Cases</Link>
          <h1 className="font-mono hr-case-title">{data.display_id}</h1>
          <p className="hr-cr-sub">
            <span>{caseTypeLabel(data)} · <Link to={`/rooms/${data.room_id}`}>{data.room_name}</Link></span>
            {fill === 'overfull' && <StatusPill tone="warn">Overfull</StatusPill>}
            {fill === 'full' && <StatusPill tone="info">Full</StatusPill>}
          </p>
        </div>
        <div className="hr-cr-actions">
          <Link to={`/cases/${displayId}/edit`} className="btn btn-outline-secondary btn-sm">Edit case</Link>
        </div>
      </header>

      {/* The hats, not a picture of the case. Every case looks identical from
          the outside, so a photo of one carried no information — and an EMPTY
          photo box was worse: a case with three hats in it showed a
          screen-filling "NO PHOTO" placeholder and pushed its actual contents
          below the fold. The grid switched to this collage; this page kept the
          uploader until now. */}
      <section className="card hr-case-hero" aria-label="What is in this case">
        <div className="hr-case-hero-media">
          <CaseCollage
            thumbs={data.hats.map(h => h.thumb_path || h.photo_path).filter((p): p is string => !!p).slice(0, 4)}
            label={data.display_id}
          />
        </div>
        <div className="hr-case-hero-facts">
          <div>
            {capacityDisplay}
            <div className="mt-2"><CaseFillMeter c={data} /></div>
          </div>
          <div className="hr-case-move">
            <label className="form-label" htmlFor="case-move-room">Room</label>
            <div className="hr-case-move-row">
              <select
                id="case-move-room"
                className="form-select"
                value={data.room_id}
                // One move at a time: two quick picks would race two PUTs, and
                // the one that landed last — not the one shown — would win.
                disabled={moveMutation.isPending}
                onChange={e => moveMutation.mutate(Number(e.target.value))}
              >
                {roomOptions.map(r => (
                  <option key={r.id} value={r.id}>{r.name}</option>
                ))}
              </select>
              <SaveState status={mutationSaveStatus(moveMutation)} savedKey={moveMutation.submittedAt} />
            </div>
            <ErrorNote of={moveMutation} what="Could not move this case" />
            {/* Otherwise a failed list leaves a picker holding only the case's
                own room — which reads as "there is nowhere else to put it". */}
            <ErrorNote of={roomsQ} what="Could not load rooms" />
          </div>
        </div>
      </section>

      <Panel
        title="Hats in this case"
        actions={<Link to={`/hats/new?caseId=${data.id}`} className="btn btn-primary btn-sm">Add hat</Link>}
      >
        {!data.hats.length ? (
          <p className="hr-cr-note">No hats in this case</p>
        ) : (
          <ul className="hr-case-hatlist">
            {data.hats.map(h => (
              <li key={h.id}>
                <Link to={`/hats/${h.id}`} className="hr-case-hatrow">
                  {h.photo_path ? (
                    <img src={tileSrc(h)} alt="" className="hr-thumb hr-case-hatrow-thumb" />
                  ) : (
                    <span className="hr-case-hatrow-ph" aria-hidden="true" />
                  )}
                  <span className="hr-case-hatrow-text">
                    <span className="hr-case-hatrow-id">{h.display_id}</span>
                    <span className="hr-case-hatrow-sub">
                      {h.style.replace(/_/g, ' ')} {h.is_beanie ? '(beanie)' : ''}
                    </span>
                  </span>
                  <span className="hr-cr-chevron" aria-hidden="true" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        title="Tag this case"
        description="Write this to an NFC sticker on the case, or print QR labels for every hat inside it."
        footer={
          <a
            href={hatLabelsUrl(data.display_id)}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-outline-secondary btn-sm"
          >Print labels for these hats</a>
        }
      >
        <TagUrlRow kind="c" ident={data.display_id} />
      </Panel>

      <Panel
        title="Delete case"
        className="hr-cr-danger"
        description={hatCount > 0
          ? `Removes the case. Its ${hatsStay} in ${data.room_name}, out of a case.`
          : 'Removes this empty case.'}
        footer={
          <button
            type="button"
            className="btn btn-outline-danger"
            onClick={handleDelete}
            disabled={removeMutation.isPending}
          >
            {removeMutation.isPending ? 'Deleting…' : 'Delete case'}
          </button>
        }
      >
        {removeMutation.isError && <ErrorNote of={removeMutation} what="Could not delete" className="" />}
      </Panel>
    </>
  );
}

/**
 * The page's shape while the case loads: title, hero, one panel. One
 * "Loading case…" status for the lot; the blocks are decoration.
 */
function CaseDetailSkeleton() {
  return (
    <div className="hr-case-skel-page">
      <span className="visually-hidden" role="status">Loading case…</span>
      <span className="hr-skeleton hr-case-skel-title" aria-hidden="true" />
      <span className="hr-skeleton hr-case-skel-hero" aria-hidden="true" />
      <span className="hr-skeleton hr-case-skel-panel" aria-hidden="true" />
    </div>
  );
}
