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

# Dispatch Plan

| # | Agent | Run? | Justification |
|---|---|---|---|
| 01 | **Roentgen** (structure) | ✅ | Always. ~80 source files across two stacks — structural map will anchor everything else. |
| 02 | **Stratum** (layers) | ✅ | Clear FastAPI layered architecture (routes → services → models). Worth confirming layer cleanliness, especially for the new pipeline orchestrator. |
| 03 | **Doppler** (flows) | ✅ | The hat-photo pipeline is multi-step + degrading + has external API + filesystem side-effects. Sequence diagrams will earn their keep here. |
| 04 | **Lumen** (deep dives) | ✅ | `claude_analysis.analyze_hat_image`, `hat_analysis_pipeline.finalize_hat_photo`, `database._run_migrations`, and the photo upload route are all subtle and high-impact. |
| 05 | **Auscultator** (signals) | ✅ | Deliberately included to surface observability gaps — this app will run unattended on a Pi. |
| 06 | **Rorschach** (intent) | ✅ | Two distinct authorial moods are visible in one repo (older CRUD vs. fresh v0.2.0 AI pipeline + UI rebuild). Worth reading both. |
| 07 | **Sentinel** (security) | ✅ | Always (Phase 2). Important because: no auth on API, secrets-in-DB pattern, file uploads, outbound HTTP to user-influenced URLs (Melin Recap), Pillow/PIL surface area, AGPL exposed by default. |
| 08 | **Scribe** (design doc) | ✅ | Always. README is good but a real design doc will help anyone forking. |
| 09 | **Prognosis** (diagnosis) | ✅ | Always. |
| 10 | **Confidant** (TL;DR) | ✅ | Always. |

## Skipped

None. The repo is small enough that running the full set is cheap, and Auscultator is genuinely useful given the unattended-Pi target.

## Constraints passed to all agents

- Read-only analysis. No code modifications.
- Anchor every finding to specific `file:line` references where possible.
- Frontend's CSS is non-trivial (~1.1k lines). Don't ignore it — it's the user-experience layer.
- Tests are mock-heavy on the AI pipeline. Don't mistake "passing tests" for "exercised production paths."
