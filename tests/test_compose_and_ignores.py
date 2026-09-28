"""Properties of the infra files that only a file scan can hold.

These are the shapes the adversarial review found by rendering compose and
reading the Dockerfile: an uv pin no updater could see, a QUIC port nothing
published, a build context that would ship the backup bundle, `/app` writable
by the runtime user.

PARSED, not grepped. The first version of this file matched substrings, and a
review mutated the files under it: `# read_only: true` (commented out) still
satisfied `"read_only: true" in compose`, a HEALTHCHECK pointed at the
always-200 `/health` still contained the word HEALTHCHECK, and a `USER root`
or a `FORWARDED_ALLOW_IPS: "*"` passed every assertion here. Compose files are
read as YAML and the Dockerfile as instructions, so a comment can no longer
stand in for the thing it describes.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.anyio


def _read(name: str) -> str:
    return (ROOT / name).read_text()


# ---- parsing helpers ----------------------------------------------------- #


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader plus Compose's merge tags (`!override`, `!reset`)."""


def _compose_tag(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_ComposeLoader.add_constructor("!override", _compose_tag)
_ComposeLoader.add_constructor("!reset", _compose_tag)


def compose(name: str) -> dict:
    # `yaml.load` with a SafeLoader SUBCLASS: safe_load's guarantees, plus the
    # two Compose tags above, and nothing that constructs arbitrary objects.
    return yaml.load(_read(name), Loader=_ComposeLoader)


def compose_files() -> list[str]:
    return sorted(p.name for p in ROOT.glob("docker-compose*.yml"))


def dockerfile_instructions() -> list[tuple[str, str]]:
    """(INSTRUCTION, arguments) in order, continuation lines joined, comments
    and the parser directive dropped — what BuildKit reads, not the prose."""
    out: list[tuple[str, str]] = []
    pending = ""
    for raw in _read("Dockerfile").splitlines():
        line = raw.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        if pending and line.startswith("#"):
            continue  # comment lines inside a continued instruction
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        full = (pending + line).strip()
        pending = ""
        keyword, _, args = full.partition(" ")
        out.append((keyword.upper(), args.strip()))
    return out


def runtime_stage() -> list[tuple[str, str]]:
    """The instructions of the LAST stage — the image that actually runs."""
    instructions = dockerfile_instructions()
    last_from = max(i for i, (k, _) in enumerate(instructions) if k == "FROM")
    return instructions[last_from:]


def _cmd_url(test) -> str:
    return " ".join(test) if isinstance(test, list) else str(test)


# ---- the Dockerfile -------------------------------------------------------- #


async def test_the_uv_pin_is_a_from_line_dependabot_can_see():
    froms = [a for k, a in dockerfile_instructions() if k == "FROM"]
    assert any(a.startswith("ghcr.io/astral-sh/uv:") and a.endswith(" AS uv") for a in froms), (
        "the uv pin must be a FROM line — Dependabot's docker ecosystem parses "
        "those and ignores `COPY --from=ghcr.io/...:tag`"
    )
    assert ("COPY", "--from=uv /uv /usr/local/bin/uv") in dockerfile_instructions()


async def test_the_runtime_user_is_not_root():
    """The last USER of the last stage decides what the container runs as.

    Nothing else enforced this: the semgrep check reports and does not block,
    and `USER root` passed the whole suite. CI also runs `id -u` in the built
    image — this is the same rule, one step earlier.
    """
    users = [a for k, a in runtime_stage() if k == "USER"]
    assert users, "the runtime stage never drops root"
    assert users[-1].split(":")[0] not in {"root", "0"}, f"the image runs as {users[-1]!r}"


async def test_nothing_the_app_executes_is_owned_by_the_runtime_user():
    """Code, venv, SPA and model are root-owned; only /data is the app's.

    The model sat in the runtime user's home and the home was chowned
    recursively, so 179 MB of weights were writable by the process that loads
    them — against this very rule.
    """
    stage = runtime_stage()
    for keyword, args in stage:
        if keyword in {"COPY", "ADD"}:
            assert "--chown" not in args, f"{keyword} {args} hands its files to the runtime user"
    chowns = []
    for keyword, args in stage:
        if keyword != "RUN":
            continue
        for command in re.split(r"&&|;", args):
            words = shlex.split(command)
            if words and words[0] == "chown":
                chowns.append([w for w in words[1:] if not w.startswith("-")][1:])
    assert chowns, "expected the /data volume to be chowned to the runtime user"
    for targets in chowns:
        assert targets == ["/data"], f"chown reaches beyond /data: {targets}"


async def test_the_model_lives_outside_the_runtime_users_home():
    """Whoever owns a directory can rename its entries, so a root-owned model
    inside the user's home can still be swapped out wholesale."""
    env = " ".join(a for k, a in runtime_stage() if k == "ENV")
    match = re.search(r"U2NET_HOME=(\S+)", env)
    assert match, "the runtime stage must point rembg at the baked model"
    home = match.group(1)
    assert not home.startswith("/home/"), f"the model is in a user's home: {home}"
    copies = [a for k, a in runtime_stage() if k == "COPY"]
    assert any(a.endswith(f" {home}") for a in copies), "the baked model is not copied to U2NET_HOME"


async def test_the_image_healthcheck_probes_readiness_not_liveness():
    """`/health` is a static 200; `/health/ready` gates on disk and workers."""
    checks = [a for k, a in dockerfile_instructions() if k == "HEALTHCHECK"]
    assert len(checks) == 1, "`docker run` and CI get no healthcheck without one in the image"
    assert "http://localhost:8000/health/ready'" in checks[0], checks[0]


async def test_the_release_build_installs_the_project_frozen():
    """`--frozen`, no fallback: a lock/manifest mismatch must FAIL the build,
    not resolve fresh unpinned versions."""
    syncs = [a for k, a in dockerfile_instructions() if k == "RUN" and "uv sync" in a]
    assert syncs, "the project is never installed"
    for args in syncs:
        assert "--frozen" in shlex.split(args.split("uv sync", 1)[1]), args


# ---- the compose files ----------------------------------------------------- #


async def test_the_base_app_root_filesystem_is_read_only():
    app = compose("docker-compose.yml")["services"]["headroom"]
    assert app.get("read_only") is True
    assert "/tmp" in app.get("tmpfs", [])
    assert app.get("stop_grace_period") == "60s", (
        "the WAL checkpoint and four workers need longer than the 10 s default "
        "to shut down cleanly"
    )


async def test_the_compose_healthcheck_probes_readiness_not_liveness():
    """This is the one the watchdog and the autoheal overlay act on."""
    test = compose("docker-compose.yml")["services"]["headroom"]["healthcheck"]["test"]
    assert "http://localhost:8000/health/ready'" in _cmd_url(test), test


async def test_the_ca_travels_with_backups_by_default():
    """Default ON: the root is installed by hand on every device, and a lost
    one means visiting them all. The env default and the code default agree."""
    env = compose("docker-compose.yml")["services"]["headroom"]["environment"]
    assert env["HEADROOM_BACKUP_INCLUDE_CA"] == "${HEADROOM_BACKUP_INCLUDE_CA:-true}"


@pytest.mark.parametrize("name", compose_files())
async def test_no_overlay_trusts_forwarded_headers_from_everyone(name):
    """`"*"` makes uvicorn take the LEFTMOST X-Forwarded-For — the one the
    client wrote — which turns the login rate limiter into a formality."""
    for service, spec in (compose(name).get("services") or {}).items():
        env = spec.get("environment") or {}
        value = env.get("FORWARDED_ALLOW_IPS") if isinstance(env, dict) else None
        assert value != "*", f"{name}: {service} trusts X-Forwarded-For from anyone"


async def test_the_letsencrypt_overlay_trusts_exactly_its_own_pinned_subnet():
    doc = compose("docker-compose.https.yml")
    trusted = doc["services"]["headroom"]["environment"]["FORWARDED_ALLOW_IPS"]
    subnet = doc["networks"]["default"]["ipam"]["config"][0]["subnet"]
    assert trusted == subnet, f"trusts {trusted!r} but the network is pinned to {subnet!r}"


@pytest.mark.parametrize("name", ["docker-compose.https-lan.yml", "docker-compose.http80.yml",
                                  "docker-compose.mdns.yml"])
async def test_host_network_overlays_trust_loopback_only(name):
    """:8000 is LAN-reachable under host networking; only Caddy on loopback
    may speak for a client. Unset means uvicorn's default, 127.0.0.1."""
    app = compose(name)["services"]["headroom"]
    assert app.get("network_mode") == "host"
    assert (app.get("environment") or {}).get("FORWARDED_ALLOW_IPS", "127.0.0.1") == "127.0.0.1"


async def test_the_letsencrypt_overlay_publishes_udp_443_for_http3():
    ports = compose("docker-compose.https.yml")["services"]["caddy"]["ports"]
    assert "443:443/udp" in ports, (
        "Caddy advertises h3 on UDP 443; without publishing it every fresh "
        "browser connection pays a QUIC timeout before falling back to h2"
    )


async def test_the_autoheal_sidecar_is_pinned_by_digest_and_waits_out_the_grace_period():
    """It holds a root-equivalent socket; what runs must be what was reviewed.

    And its restarts must honor the app's shutdown window: autoheal's default
    stop timeout is Docker's 10 s, which kills a WAL checkpoint mid-write.
    """
    doc = compose("docker-compose.autoheal.yml")["services"]["autoheal"]
    assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", doc["image"]), doc["image"]
    grace = compose("docker-compose.yml")["services"]["headroom"]["stop_grace_period"]
    assert int(doc["environment"]["AUTOHEAL_DEFAULT_STOP_TIMEOUT"]) >= int(grace.rstrip("s"))


async def test_the_rclone_config_is_a_writable_directory_not_a_read_only_file():
    """rclone rewrites its config on every OAuth refresh — via a temp file
    beside it — and Box refresh tokens are single-use. A read-only file mount
    works exactly once."""
    app = compose("docker-compose.backup-rclone.yml")["services"]["headroom"]
    config_path = app["environment"]["RCLONE_CONFIG"]
    target_dir = str(Path(config_path).parent)

    def _target_and_mode(mount: str) -> tuple[str, str]:
        # Read from the RIGHT: the source may hold `${VAR:-default}`, colons
        # and all; the container path and the mode never do.
        head, _, last = mount.rpartition(":")
        if last in {"ro", "rw", "z", "Z"}:
            return head.rpartition(":")[2], last
        return last, "rw"

    matching = [_target_and_mode(m) for m in app["volumes"] if _target_and_mode(m)[0] == target_dir]
    assert matching, f"nothing mounts the directory holding {config_path}"
    assert matching[0][1] != "ro", "the rclone config directory is mounted read-only"
    assert "--config" not in app["environment"]["HEADROOM_BACKUP_UPLOAD_CMD"], (
        "RCLONE_CONFIG is the one place the path is stated"
    )


# ---- the CI gates that hold the rules above ----------------------------------- #


def _ci_steps(job: str) -> list[dict]:
    doc = yaml.safe_load(_read(".github/workflows/ci.yml"))
    return doc["jobs"][job]["steps"]


async def test_ci_asks_the_built_image_who_it_runs_as():
    """The file test above reads the Dockerfile; this gate reads the IMAGE,
    where a base-image `USER` or an entrypoint could still make it root."""
    runs = [s.get("run", "") for s in _ci_steps("docker")]
    build = next(i for i, r in enumerate(runs) if "docker build -t headroom:ci" in r)
    check = next(
        (i for i, r in enumerate(runs) if "docker run --rm headroom:ci id -u" in r and '!= "0"' in r),
        None,
    )
    assert check is not None and check > build, "CI never checks the built image's uid"
    assert "-writable" in runs[check], "CI never checks the image's code is read-only to the app"


async def test_ci_lints_the_rules_of_hooks_before_the_tests():
    """A hook after an early return passes tsc and every unit test."""
    runs = [s.get("run", "") for s in _ci_steps("frontend")]
    assert "npm run lint" in runs
    assert runs.index("npm run lint") < runs.index("npm test")


# ---- the Caddyfiles, and the build context ----------------------------------- #


async def test_the_letsencrypt_overlay_sets_hsts():
    assert "Strict-Transport-Security" in _read("Caddyfile.https"), (
        "the app's middleware leaves HSTS to Caddy on the internet-facing overlay"
    )


async def test_both_caddyfiles_compress_the_bundle():
    assert "encode zstd gzip" in _read("Caddyfile")
    assert "encode zstd gzip" in _read("Caddyfile.https")


@pytest.mark.parametrize("pattern", ["backups/", "*.pem", "*.key", "*.db-wal", "hardware"])
async def test_the_dockerignore_excludes_the_credential_bundle(pattern):
    assert pattern in _read(".dockerignore").splitlines(), (
        f"{pattern} is uploaded in the build context without this"
    )


@pytest.mark.parametrize("pattern", ["backups/", "*.pem", "*.key"])
async def test_the_gitignore_excludes_secrets_and_backups(pattern):
    assert pattern in _read(".gitignore").splitlines()


async def test_the_engines_floor_is_enforced_not_just_warned():
    npmrc = _read("frontend/.npmrc")
    assert "engine-strict=true" in npmrc.splitlines(), (
        "without this `npm ci` only WARNS on a too-old Node; setup.sh's comment "
        "claims it errors"
    )


async def test_the_image_build_reads_npmrc_before_it_installs():
    """`engine-strict` only governs an install that can SEE the file. The image
    copied `.npmrc` with the rest of the frontend tree, after `npm ci` had run,
    so the build never applied the check the file exists for."""
    lines = _read("Dockerfile").splitlines()
    ci = next(i for i, line in enumerate(lines) if "npm ci" in line and not line.lstrip().startswith("#"))
    copies = [
        line for line in lines[:ci]
        if line.startswith("COPY ") and "frontend/.npmrc" in line
    ]
    assert copies, "frontend/.npmrc must be COPYed before the `npm ci` step"


async def test_both_manifests_declare_the_license():
    assert 'license = "AGPL-3.0-or-later"' in _read("pyproject.toml")
    assert '"license": "AGPL-3.0-or-later"' in _read("frontend/package.json")
