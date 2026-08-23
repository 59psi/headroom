import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getGuestView, setGuestView } from '../../api/settings';

/**
 * The switch that decides whether the collection is readable without an
 * account.
 *
 * Says plainly what it exposes and what it withholds. "Guest mode" on its own
 * is not enough to decide with — the question anyone actually has is *what
 * will they see*, and the honest answer is short enough to print.
 */
export function GuestViewCard() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ['settings', 'guest-view'],
    queryFn: getGuestView,
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => setGuestView(enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', 'guest-view'] });
      qc.invalidateQueries({ queryKey: ['auth', 'status'] });
    },
  });

  const enabled = data?.enabled ?? false;

  return (
    <div className="card mb-3">
      <div className="card-body">
        <h5 className="card-title">Guest browsing</h5>
        <p className="text-secondary small">
          Adds a “browse as a guest” link to the login screen. Anyone who can
          reach Headroom can then look through the collection and search it,
          without an account.
        </p>

        <div className="form-check form-switch mb-2">
          <input
            id="guest-view-toggle"
            aria-label="Allow guest browsing"
            className="form-check-input"
            type="checkbox"
            role="switch"
            checked={enabled}
            disabled={toggle.isPending}
            onChange={e => toggle.mutate(e.target.checked)}
          />
          <label className="form-check-label" htmlFor="guest-view-toggle">
            {enabled ? 'Guests can browse' : 'Off — sign-in required'}
          </label>
        </div>

        <p className="text-secondary small mb-0">
          Guests see photos, brand, model, style, colours and where a hat lives.
          They do <strong>not</strong> see prices, what you paid, what anything
          sold for, your notes, or anything you've disposed of — those aren't
          hidden in the page, they're never sent. Guests cannot change anything.
        </p>
      </div>
    </div>
  );
}
