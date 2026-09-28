"""Facts the operator docs state, pinned to the code that makes them true.

`test_docs_consistency` holds the docs to the default Claude model. This file
does the same for four facts that drifted while every test stayed green:

* **Where things are in Settings.** 2.80 rebuilt Settings into five sections,
  and README, USAGE and OPERATIONS went on sending people to "Settings →
  Account", "Settings → Tags & labels" and "Settings → Trust this device" —
  cards that now live one level down. A path is only useful if it is the
  path, so every `Settings → <section> → <card>` in the three docs is checked
  against `SettingsPage.tsx`'s `SECTIONS`, which is what renders them.
* **Which knobs Docker does not forward.** OPERATIONS said "every
  `HEADROOM_*` knob below is listed in the compose file", beside a row for
  `HEADROOM_REMBG_MODEL`, which is deliberately not forwarded — so a `.env`
  setting did nothing. The deliberate exceptions live in
  `test_env_passthrough.NOT_FORWARDED`; both docs must name each one.
* **Which Node the bare-metal setup accepts.** README said "Node 22.22+ ...
  the highest any dependency declares" while jsdom 30 refused 22.22.0–22.22.1,
  24.0–24.14 and 25, so `npm ci` died on versions the README promised.
  `setup.sh` states the accepted set as data (and `test_toolchain_pins` holds
  it to the lockfile); the README must state that same set.
* **What a failed model fetch means.** The Dockerfile's build warning must be
  the one OPERATIONS tells operators to watch for, and must not promise the
  runtime download that the read-only image cannot perform.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.test_env_passthrough import NOT_FORWARDED

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "docs/USAGE.md", "docs/OPERATIONS.md")
SETTINGS_PAGE = ROOT / "frontend/src/pages/SettingsPage.tsx"
SETUP = ROOT / "scripts/setup.sh"


def _sections() -> dict[str, list[str]]:
    """Section label → its card names, in the order `SECTIONS` renders them.

    Read from the source rather than restated here: a copy of the roster in
    this file would be one more thing to drift, which is the whole problem.
    """
    source = SETTINGS_PAGE.read_text()
    table = source[source.index("export const SECTIONS"):]
    table = table[: table.index("\n];")]
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for label, card in re.findall(r"label: '([^']+)'|name: '([^']+)'", table):
        if label:
            current = sections.setdefault(label, [])
        elif current is not None:
            current.append(card)
    return sections


def _prose(doc: str) -> str:
    """The doc as running text: emphasis and quote markers gone, lines joined.

    A path is often broken across a line (`Settings → Device\\n→ Account`) or
    set in bold or italics, and neither changes what it names.
    """
    text = (ROOT / doc).read_text()
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    text = text.replace("*", "").replace("`", "")
    return re.sub(r"\s+", " ", text)


def _settings_paths(text: str) -> list[list[str]]:
    """Every `Settings → a → b …` in `text`, as its segments after `Settings`."""
    paths = []
    for m in re.finditer(r"Settings\s*→\s*((?:[^→]{1,80}?→\s*){0,3}[^→]{1,80})", text):
        paths.append([seg.strip() for seg in m.group(1).split("→")])
    return paths


def _starts_with(segment: str, name: str) -> bool:
    return re.match(rf"{re.escape(name)}(?![\w-])", segment, flags=re.I) is not None


async def test_the_section_roster_parses():
    """Guard the guard: a parser that read nothing would pass every doc."""
    sections = _sections()
    assert list(sections) == ["Analysis", "Data", "Sharing", "Device", "Upkeep"]
    assert "Account" in sections["Device"]
    assert "Tags & labels" in sections["Sharing"]


@pytest.mark.parametrize("doc", DOCS)
async def test_every_settings_path_in_the_docs_is_real(doc):
    sections = _sections()
    all_cards = {card: label for label, cards in sections.items() for card in cards}
    problems = []
    for segments in _settings_paths(_prose(doc)):
        first = segments[0]
        label = next((s for s in sections if _starts_with(first, s)), None)
        if label is None:
            # Not a Headroom section: either a phone's own Settings app
            # ("Settings → General → About") — fine — or a Headroom card named
            # with its section left out, which is the drift this catches.
            card = next((c for c in all_cards if _starts_with(first, c)), None)
            if card is not None:
                problems.append(
                    f"'Settings → {first[:40]}' skips the section: "
                    f"write 'Settings → {all_cards[card]} → {card}'"
                )
            continue
        if len(segments) > 1:
            second = segments[1]
            if not any(_starts_with(second, card) for card in sections[label]):
                problems.append(
                    f"'Settings → {label} → {second[:40]}' names no card in "
                    f"{label} (cards: {', '.join(sections[label])})"
                )
    assert problems == [], f"{doc}:\n" + "\n".join(problems)


@pytest.mark.parametrize("doc", ["README.md", "docs/OPERATIONS.md"])
async def test_the_docs_name_every_knob_docker_does_not_forward(doc):
    """Each deliberate exception is named where the doc explains forwarding.

    Checked inside that one paragraph, not anywhere in the file — every one of
    these names also has a table row, so a whole-file search would pass with
    the explanation deleted.
    """
    text = _prose(doc)
    start = text.index("Under Docker")
    paragraph = text[start : start + 1400]
    missing = [name for name in NOT_FORWARDED if name not in paragraph]
    assert missing == [], f"{doc} no longer says these are not forwarded: {missing}"


async def test_the_build_warning_is_the_one_operations_says_to_watch_for():
    """OPERATIONS tells an operator to watch the build output for the
    model-fetch warning and to rebuild when it appears, because a missing
    model cannot be fetched at runtime (root-owned model dir, read-only root
    filesystem). The warning itself said "the app will download it on first
    use" — the one line read in the moment argued against the doc's advice,
    and against the Dockerfile's own comment above it."""
    dockerfile = (ROOT / "Dockerfile").read_text()
    warning = re.search(
        r'echo "(WARNING: could not pre-cache the rembg model[^"]*)"', dockerfile
    ).group(1)
    quoted = re.search(
        r"Watch for (WARNING: could not pre-cache the rembg model)",
        _prose("docs/OPERATIONS.md"),
    ).group(1)

    assert warning.startswith(quoted), (warning, quoted)
    assert "first use" not in warning, warning
    assert "rebuild" in warning, warning


async def test_the_readme_states_the_node_versions_setup_accepts():
    setup = SETUP.read_text()
    minimums = re.search(r'^NODE_LINE_MINIMUMS="([^"]+)"$', setup, re.M).group(1).split()
    open_from = re.search(r"^NODE_OPEN_FROM_MAJOR=(\d+)$", setup, re.M).group(1)

    def spelled(version: str) -> str:
        major, minor, patch = version.split(".")
        shown = f"{major}.{minor}" if patch == "0" else version
        return f"{shown}+ on the {major} line"

    expected = ", ".join(spelled(v) for v in minimums) + f", or {open_from}+"
    assert expected in _prose("README.md"), (
        f"README must state the Node set setup.sh accepts: '{expected}'"
    )
