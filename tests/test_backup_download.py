"""The two promises OPERATIONS §4 makes about the one-click backup download:
"the download endpoint writes an audit row on every manual download", and
`?include_uploads=false` gives "a database-only archive".

Both survived a mutation of the full suite: renaming the audit kind, and
dropping `include_uploads` from the uploads condition so the "DB-only" archive
shipped every photo anyway.
"""

from __future__ import annotations

import io
import tarfile

import pytest

pytestmark = pytest.mark.anyio


async def test_every_download_is_audited(client):
    """The archive holds the whole database — every key, token and hash — so
    a full-dataset export must never be invisible."""
    for include in ("true", "false"):
        resp = await client.get("/api/admin/backup", params={"include_uploads": include})
        assert resp.status_code == 200

    rows = (await client.get("/api/admin/activity-log")).json()
    downloads = [r for r in rows if r["kind"] == "backup.download"]
    assert len(downloads) == 2, [r["kind"] for r in rows]
    summaries = sorted(r["summary"] for r in downloads)
    assert "(db-only)" in summaries[0] and "(full)" in summaries[1], summaries


async def test_a_database_only_download_carries_no_photos(client):
    from headroom.config import settings

    (settings.upload_dir / "hats" / "a-photo.png").write_bytes(b"\x89PNG not really")

    full = await client.get("/api/admin/backup")
    db_only = await client.get("/api/admin/backup", params={"include_uploads": "false"})

    def names(resp) -> list[str]:
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
            return tar.getnames()

    assert any(n.startswith("data/uploads/") for n in names(full)), "the premise"
    photos = [n for n in names(db_only) if n == "data/uploads" or n.startswith("data/uploads/")]
    assert photos == [], f"a database-only archive shipped the photo tree: {photos}"
