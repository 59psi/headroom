"""`scripts/upgrade.sh`: the release-note checklist, as code.

Each step is a function the script defines when sourced; these run them in a
throwaway `.env` and repo, with `docker` / `timedatectl` stubbed on PATH, so
nothing here touches a real install. The full run (pull, build, health, Caddy)
is exercised against the production Pi, not in the suite.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "upgrade.sh"


def _stub(bindir: Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path):
    repo = tmp_path / "headroom"
    repo.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    def run(commands: str, *, check=True):
        env = {
            "PATH": f"{bindir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(home),
            "REPO_DIR": str(repo),
            "ENV_FILE": str(repo / ".env"),
        }
        return subprocess.run(
            ["bash", "-c", f"source '{SCRIPT}'; {commands}"],
            capture_output=True, text=True, env=env, check=check,
        )

    return {"repo": repo, "bin": bindir, "home": home, "run": run}


def _env(sandbox) -> dict[str, str]:
    path = sandbox["repo"] / ".env"
    if not path.exists():
        return {}
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


async def test_sourcing_the_script_runs_nothing(sandbox):
    result = sandbox["run"]("echo sourced")
    assert result.stdout.strip() == "sourced"
    assert not (sandbox["repo"] / ".env").exists()


async def test_env_set_replaces_one_key_and_keeps_the_rest(sandbox):
    (sandbox["repo"] / ".env").write_text("HEADROOM_BUILD_SHA=abc\nTZ=UTC\nOTHER=x=y\n")
    sandbox["run"]("env_set TZ America/Los_Angeles; env_set NEW 1")
    text = (sandbox["repo"] / ".env").read_text()
    assert text.count("TZ=") == 1
    assert _env(sandbox) == {
        "HEADROOM_BUILD_SHA": "abc", "OTHER": "x=y", "TZ": "America/Los_Angeles", "NEW": "1",
    }
    assert sandbox["run"]("env_get OTHER").stdout.strip() == "x=y"


def _docker_ls(sandbox, rows):
    payload = json.dumps(rows)
    _stub(sandbox["bin"], "docker", f"""
if [ "$1 $2" = "compose ls" ]; then echo '{payload}'; exit 0; fi
exit 1
""")


async def test_the_running_overlays_are_recorded_so_a_bare_command_keeps_them(sandbox):
    """A bare `docker compose up` on an HTTPS host reverted to the base config.
    With COMPOSE_FILE in .env, every later command keeps the overlays."""
    repo = sandbox["repo"]
    _docker_ls(sandbox, [
        {"Name": "other", "ConfigFiles": "/elsewhere/docker-compose.yml"},
        {"Name": "headroom", "ConfigFiles": f"{repo}/docker-compose.yml,{repo}/docker-compose.https-lan.yml"},
    ])
    sandbox["run"]("ensure_compose_files")
    assert _env(sandbox)["COMPOSE_FILE"] == "docker-compose.yml:docker-compose.https-lan.yml"


async def test_an_existing_compose_file_setting_is_left_alone(sandbox):
    (sandbox["repo"] / ".env").write_text("COMPOSE_FILE=docker-compose.yml:docker-compose.https.yml\n")
    _docker_ls(sandbox, [{"Name": "headroom", "ConfigFiles": "/x/docker-compose.yml"}])
    sandbox["run"]("ensure_compose_files")
    assert _env(sandbox)["COMPOSE_FILE"] == "docker-compose.yml:docker-compose.https.yml"


async def test_a_failing_compose_ls_does_not_abort_the_upgrade(sandbox):
    """The script runs under `set -euo pipefail`; a `docker compose ls` that
    errors must read as "nothing running", not end the upgrade half-way."""
    _stub(sandbox["bin"], "docker", 'echo "unknown flag: --format" >&2; exit 1\n')
    result = sandbox["run"]("set -euo pipefail; ensure_compose_files; echo still-here")
    assert "still-here" in result.stdout
    assert "COMPOSE_FILE" not in _env(sandbox)


async def test_with_nothing_running_no_compose_file_is_invented(sandbox):
    _docker_ls(sandbox, [])
    sandbox["run"]("ensure_compose_files")
    assert "COMPOSE_FILE" not in _env(sandbox)


async def test_an_explicit_time_zone_is_written(sandbox):
    sandbox["run"]("ensure_timezone America/Los_Angeles")
    assert _env(sandbox)["TZ"] == "America/Los_Angeles"


async def test_an_unknown_time_zone_is_refused(sandbox):
    if not Path("/usr/share/zoneinfo").is_dir():
        pytest.skip("no zoneinfo database to validate against")
    result = sandbox["run"]("ensure_timezone Mars/Olympus_Mons", check=False)
    assert result.returncode != 0
    assert "unknown time zone" in result.stderr
    assert "TZ" not in _env(sandbox)


async def test_a_utc_host_is_not_taken_as_the_owners_time_zone(sandbox):
    """Most Pis are on UTC because nobody set them, not because the owner lives
    on the meridian — guessing UTC would pin every scan to the wrong day."""
    _stub(sandbox["bin"], "timedatectl", 'echo "Etc/UTC"\n')
    result = sandbox["run"]("ensure_timezone")
    assert "TZ" not in _env(sandbox)
    assert "--tz" in result.stderr


async def test_a_non_utc_host_zone_is_used(sandbox):
    _stub(sandbox["bin"], "timedatectl", 'echo "Europe/Berlin"\n')
    sandbox["run"]("ensure_timezone")
    assert _env(sandbox)["TZ"] == "Europe/Berlin"


async def test_an_existing_time_zone_is_kept(sandbox):
    (sandbox["repo"] / ".env").write_text("TZ=Asia/Tokyo\n")
    _stub(sandbox["bin"], "timedatectl", 'echo "Europe/Berlin"\n')
    sandbox["run"]("ensure_timezone")
    assert _env(sandbox)["TZ"] == "Asia/Tokyo"


async def test_the_old_rclone_config_moves_to_the_writable_directory(sandbox):
    old = sandbox["home"] / ".config" / "rclone" / "rclone.conf"
    old.parent.mkdir(parents=True)
    old.write_text("[box]\ntype = box\n")
    (sandbox["repo"] / ".env").write_text(
        "COMPOSE_FILE=docker-compose.yml:docker-compose.backup-rclone.yml\n"
    )
    sandbox["run"]("ensure_rclone_config")
    new = sandbox["home"] / ".config" / "headroom-rclone" / "rclone.conf"
    assert new.read_text() == "[box]\ntype = box\n"
    assert oct(new.stat().st_mode & 0o777) == "0o600"


async def test_a_config_already_in_the_new_place_is_never_overwritten(sandbox):
    old = sandbox["home"] / ".config" / "rclone" / "rclone.conf"
    old.parent.mkdir(parents=True)
    old.write_text("old\n")
    new = sandbox["home"] / ".config" / "headroom-rclone" / "rclone.conf"
    new.parent.mkdir(parents=True)
    new.write_text("refreshed token\n")
    (sandbox["repo"] / ".env").write_text("COMPOSE_FILE=docker-compose.backup-rclone.yml\n")
    sandbox["run"]("ensure_rclone_config")
    assert new.read_text() == "refreshed token\n"


async def test_without_the_rclone_overlay_nothing_is_copied(sandbox):
    old = sandbox["home"] / ".config" / "rclone" / "rclone.conf"
    old.parent.mkdir(parents=True)
    old.write_text("x\n")
    (sandbox["repo"] / ".env").write_text("COMPOSE_FILE=docker-compose.yml\n")
    sandbox["run"]("ensure_rclone_config")
    assert not (sandbox["home"] / ".config" / "headroom-rclone").exists()


async def test_a_caddy_serving_a_stale_caddyfile_is_restarted(sandbox, tmp_path):
    """`git pull` replaces the Caddyfile's inode; the bind-mounted container
    keeps serving the old one until restarted. Only a difference restarts."""
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text("new config\n")
    restarted = tmp_path / "restarted"
    _stub(sandbox["bin"], "docker", f"""
case "$1" in
  ps) printf 'headroom\\nheadroom-caddy\\n' ;;
  inspect) echo "{caddyfile}" ;;
  exec) echo "0123456789abcdef0123456789abcdef  /etc/caddy/Caddyfile" ;;
  restart) echo "$2" >> "{restarted}" ;;
esac
""")
    sandbox["run"]("refresh_caddy")
    assert restarted.read_text().split() == ["headroom-caddy"]


async def test_a_caddy_already_serving_the_file_on_disk_is_left_running(sandbox, tmp_path):
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text("same\n")
    # Looked up on the sandbox's own PATH (macOS keeps it in /sbin).
    if shutil.which("md5sum", path="/usr/bin:/bin:/usr/sbin:/sbin") is None:
        pytest.skip("md5sum not available")
    digest = subprocess.run(
        ["bash", "-c", f"PATH=/usr/bin:/bin:/usr/sbin:/sbin md5sum < '{caddyfile}' | cut -d' ' -f1"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    restarted = tmp_path / "restarted"
    _stub(sandbox["bin"], "docker", f"""
case "$1" in
  ps) echo headroom-caddy ;;
  inspect) echo "{caddyfile}" ;;
  exec) echo "{digest}  /etc/caddy/Caddyfile" ;;
  restart) echo "$2" >> "{restarted}" ;;
esac
""")
    sandbox["run"]("refresh_caddy")
    assert not restarted.exists()


@pytest.mark.parametrize(
    ("help_text", "expected"),
    [
        ("--max-used-space bytes   Maximum amount", "builder prune -f --max-used-space 6GB"),
        ("--keep-storage bytes   Amount of disk", "builder prune -f --keep-storage 6GB"),
        ("--filter filter   Provide filter values", "builder prune -f --filter until=168h"),
    ],
)
async def test_the_build_cache_is_capped_by_size_where_docker_can(sandbox, tmp_path, help_text, expected):
    """An age filter freed nothing on the Pi: a box that upgrades weekly has
    no cache older than a week. A size cap keeps the newest layers only."""
    calls = tmp_path / "calls"
    _stub(sandbox["bin"], "docker", f"""
if [ "$*" = "builder prune --help" ]; then echo "{help_text}"; exit 0; fi
echo "$*" >> "{calls}"
""")
    sandbox["run"]("prune_build_cache")
    assert calls.read_text().strip() == expected


async def test_help_prints_the_whole_header(sandbox):
    result = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True, check=True)
    assert result.stdout.startswith("Upgrade a Docker install of Headroom in place")
    assert "HEADROOM_BUILD_CACHE_CAP" in result.stdout
    assert "tests/test_upgrade_script.py" in result.stdout  # the header's last line
    assert "set -euo pipefail" not in result.stdout


async def test_uncommitted_changes_stop_the_upgrade(sandbox):
    repo = sandbox["repo"]
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    (repo / "Caddyfile").write_text("a\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    assert sandbox["run"]("require_clean_checkout", check=False).returncode == 0
    (repo / "Caddyfile").write_text("edited\n")
    result = sandbox["run"]("require_clean_checkout", check=False)
    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr
