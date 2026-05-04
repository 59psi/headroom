---
agent: triage
version: 1.0
target: /Users/brandon/Things/Headroom @ a2efd86
confidence: high
findings: []
open_questions: []
red_flags: []
artifacts: []
---

# Open Questions (union across all agents)

_42 unique open questions surfaced across 11 agents._

## auscultator

- Does the operator actually `docker logs -f headroom` on the Pi, or do they only look when something is reported broken? If the latter, the WARNING-only-to-stdout pattern is effectively /dev/null.
- Is there an external uptime check pointed at the Pi (UptimeRobot, etc.)? If yes, /health is sufficient as liveness. If no, even container restart-loops go undetected.
- Does the Pi's Docker daemon have a json-file log rotation cap configured at the daemon level (/etc/docker/daemon.json)? Compose doesn't set one.
- Single-user app — is alerting even desired? Or is 'I'll notice when I try to upload a hat' acceptable?

## confidant

- Is HEADROOM_ANTHROPIC_MODEL overridden in the actual Pi deployment, or is every Claude analysis silently failing right now?
- Has the operator ever observed a successful end-to-end Claude analysis since v0.2.0 was deployed?
- Is the rembg session actually thread-unsafe, or is the asyncio.Lock defensive over-engineering that defeats concurrency for nothing?
- Is the Pi exposed beyond the trusted home LAN (Tailscale, Cloudflare Tunnel, public IP)? If so, the threat model collapses.
- Is the operator actually tailing docker logs, or is the WARNING-only-to-stdout pattern effectively /dev/null?

## doppler

- Is rembg session truly safe to use concurrently? The asyncio.Lock suggests not; this is a hard serialization bottleneck for image throughput.
- Why does process_image (Pillow) NOT use to_thread when remove_background does? Both are CPU-bound and block the loop.
- When rembg returns a PNG path, the JPEG is unlinked. If Claude analysis then crashes mid-call, the hat row still has photo_path set to the PNG — but if remove_background returned None, photo_path points to the JPEG. The fallback is silent, so observability of degradation is limited to log warnings.
- Anthropic 'claude-sonnet-4-6' (config.py:15) — is this a typo for sonnet-4.5 or a forward-dated model id? Worth flagging to Sentinel.
- delete_case unassigns hats but does NOT clean up orphan hats from the gallery — they become case_id=NULL hats. Is this intentional (drawer of unassigned hats) or a leak?

## lumen

- Does config_settings.anthropic_model='claude-sonnet-4-6' actually resolve at the API? Anthropic's id scheme is typically 'claude-sonnet-4-5-20250929' or 'claude-sonnet-4-6-20251001'. If the SDK requires a dated suffix or alias mapping, every analysis call 404s with no integration test catching it.
- Why is the Hat.colors clear() in _apply_analysis safe given the hat was loaded via selectinload but committed in the route layer? cascade='all, delete-orphan' on the relationship should DELETE orphaned HatColor rows on flush — but only if the session is tracking them. Worth verifying that finalize_hat_photo + later db.commit() actually emits the DELETEs (it should via autoflush).
- The lifespan creates upload_dir/{cases,hats,branding} but ensure_default_room is called from init_db — what happens on a totally fresh boot when models import order matters? __all_models__ is imported inside init_db; if any other code path touches Base.metadata before init_db runs, create_all behavior could differ.

## prognosis

- Is `HEADROOM_ANTHROPIC_MODEL` set in the actual Pi deployment? If yes, the bad default is dormant. If no, every analysis is currently failing in production and the operator hasn't noticed because the photo-save still 'succeeds'.
- Has the operator ever observed a successful end-to-end Claude analysis since v0.2.0 was deployed? The absence of a real-path test means this is an empirical question, not a code-review one.
- Is the rembg session actually unsafe under concurrent inference, or is `_session_lock` defensive over-engineering? If safe, dropping the lock unlocks real concurrency at no risk.
- Are SQLite writes serialized enough by aiosqlite that the long-held AsyncSession during photo upload (~5–30s holding a connection while bg-removal + network IO run) is harmless? On Pi/SQLite yes; if the DB ever moves, no.

## roentgen

- INFERENCE: Layout looks like a hexagonal/onion arrangement (routes are thin adapters, services hold logic, models are persistence) — this is shape-only inference, not confirmed by docs or interfaces.
- INFERENCE: Pricing/resale fields on Hat model and Melin Recap link builder appear to be a single feature pair, but no explicit module groups them.
- Are the two ad-hoc imports inside reanalyze_hat() (claude_analysis, hat_analysis_pipeline._apply_analysis, settings_service) intentional lazy-loads or accidental? The same modules are already top-level imports elsewhere in routes/hats.py.
- frontend/headroom.db exists at frontend/ root — unclear whether this is a stray/leftover or referenced by tooling.

## rorschach

- Was the synthwave CSS hand-tuned by Brandon or generated by Claude? It's stylistically coherent and feels like the work of someone with strong taste, but the volume + perfect token discipline is also exactly what a vision-prompted LLM produces. The sunset stripe + neonFlicker keyframe + 'JetBrains Mono for hex values' choices read as human aesthetic decisions.
- Did Brandon ever read the v0.2.0 diff carefully? The reanalyze_hat route (routes/hats.py:188-194) does function-local imports — that's an LLM trying to avoid circular imports it didn't actually need to avoid. A code reviewer would have moved them to module top.
- Is the duplicate `if img.mode in ('RGBA', 'P'): img = img.convert('RGB')` / `elif img.mode != 'RGB': img = img.convert('RGB')` branching in utils/photo.py:25-28 a relic of an older logic, or a never-noticed dead branch? Both branches do the same thing.

## scribe

- Anthropic model id 'claude-sonnet-4-6' (config.py:15) does not match Anthropic's published id scheme — verify against SDK before relying on it in prod (Lumen, Doppler).
- The frontend/headroom.db file at the frontend root — leftover or live? (Roentgen)
- Is the asyncio.Lock around rembg's to_thread necessary? It serialises inference globally and defeats the offload (Lumen, Doppler).
- Does the operator actually tail docker logs, or is the WARNING-only-to-stdout pattern effectively /dev/null? (Auscultator)
- Should reanalyze_hat delegate fully to a public hat_analysis_pipeline.reanalyze() rather than reach for the private _apply_analysis helper? (Stratum, Lumen, Rorschach)

## sentinel

- Is the /uploads/ static mount intended to be world-readable? Anyone with TCP port access can enumerate uploaded photos (filenames are uuid4 so not directory-listed, but if the photo URL ever leaks via analytics/referer/screenshot it is forever public). Acceptable for personal Pi but document it.
- If the Pi is exposed via Tailscale/Cloudflare Tunnel/reverse-proxy publicly, every API endpoint is anonymous — including DELETE /api/settings/api-key. Should the README explicitly require an upstream auth proxy (basic auth, oauth2-proxy, Tailscale-only) before public exposure?
- Does the Settings UI expose the masked key on the dashboard / hat-detail pages? The mask reveals 5 prefix chars (which are deterministic 'sk-an' for Anthropic keys) plus 4 suffix chars. Combined with brute force or a key-leak elsewhere, the suffix is a plaintext oracle. Could mask to '•••' instead.
- frontend/headroom.db at the repo root (per Roentgen) — is that a leftover dev DB? If it contains a real key it would be a secret-in-git risk.

## stratum

- Should `update_hat_colors` be moved into `hat_service` to remove the route-layer ORM access at `routes/hats.py:124-138`?
- Should `reanalyze_hat` route delegate fully to a `hat_analysis_pipeline.reanalyze(hat)` function rather than re-implementing the orchestration inline (currently uses `_apply_analysis` private helper)?
- Is the lack of any auth intentional for a single-user-on-Pi deployment? If exposed publicly, the `/api/settings/api-key` endpoint is unauthenticated and lets anyone read the masked key, set a new key, or delete it.

## triage

- Is this a single-user or shared deployment? README implies single-user-on-Pi but there's no auth at all on the API.
- What hat collection size is realistic? (1k? 10k?) — affects scaling concerns.
