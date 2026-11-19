import sys

import httpx
import pytest

from app.api import proposals as api_mod
from app.main import app
from app.security.paths import PathRejected, resolve_inside
from app.security.proposals import store
from app.tools.apply import apply_change, undo_change

OLD = "def health():\n    return {'status': 'ok'}"
NEW = "def health():\n    return {'status': 'ok', 'v': 1}"


def change(**kw):
    base = {"path": "app/main.py", "action": "modify", "old": OLD, "new": NEW, "syntax": "ok", "verified": True,
            "line": 2, "explanation": "x", "diff": "d", "syntax_error": ""}
    return {**base, **kw}


@pytest.fixture
def root(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_bytes(b"import os\n\n" + OLD.replace("\n", "\n").encode() + b"\n")
    return tmp_path


# ---- path safety -----------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["../x.py", "a/../../x.py", "/etc/x.py", "C:\\Windows\\x.py", ".env", ".env.local",
                                 "node_modules/a.js", ".git/config.txt", "a.exe", "x.py:stream", "", "id_rsa"])
def test_dangerous_paths_are_rejected(root, bad):
    with pytest.raises(PathRejected):
        resolve_inside(root, bad)


def test_normal_and_backslash_paths_are_accepted(root):
    assert resolve_inside(root, "app/new/file.py").is_relative_to(root.resolve())
    assert resolve_inside(root, "app\\new\\file.py").is_relative_to(root.resolve())


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_symlink_escape_is_rejected(root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (root / "link").symlink_to(outside)
    with pytest.raises(PathRejected):
        resolve_inside(root, "link/evil.py")


# ---- applying and undoing --------------------------------------------------------------------

def test_apply_replaces_exactly_and_undo_restores_bytes(root):
    path = root / "app" / "main.py"
    original = path.read_bytes()
    out = apply_change(root, change())
    assert out.status == "applied" and b"'v': 1" in path.read_bytes()
    assert path.read_bytes().startswith(b"import os\n\n")  # untouched lines stay untouched
    assert undo_change(out.undo).status == "undone" and path.read_bytes() == original


def test_windows_line_endings_are_preserved(root):
    path = root / "app" / "main.py"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    out = apply_change(root, change())
    data = path.read_bytes()
    assert out.status == "applied" and b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")


def test_trailing_whitespace_differences_still_match(root):
    path = root / "app" / "main.py"
    path.write_bytes(path.read_bytes().replace(b"def health():", b"def health():   "))
    assert apply_change(root, change()).status == "applied"


def test_not_found_and_ambiguous_are_refused(root):
    assert "not found" in apply_change(root, change(old="def nothing():")).detail
    path = root / "app" / "main.py"
    path.write_bytes(path.read_bytes() * 2)
    assert "ambiguous" in apply_change(root, change()).detail


def test_syntax_error_and_missing_file_are_refused(root):
    assert apply_change(root, change(syntax="error")).status == "skipped"
    assert "does not exist" in apply_change(root, change(path="app/none.py")).detail


def test_create_makes_file_but_never_overwrites(root):
    c = change(path="app/new_dir/helper.py", action="create", old="", new="x = 1")
    out = apply_change(root, c)
    assert out.status == "applied" and (root / "app/new_dir/helper.py").read_text() == "x = 1\n"
    assert "refusing to overwrite" in apply_change(root, c).detail
    assert undo_change(out.undo).status == "undone" and not (root / "app/new_dir/helper.py").exists()


def test_dry_run_writes_nothing(root):
    before = (root / "app" / "main.py").read_bytes()
    assert apply_change(root, change(), dry_run=True).status == "would_apply"
    assert (root / "app" / "main.py").read_bytes() == before


def test_undo_refuses_when_file_changed_afterwards(root):
    out = apply_change(root, change())
    (root / "app" / "main.py").write_text("someone edited this\n")
    assert undo_change(out.undo).status == "skipped"
    assert (root / "app" / "main.py").read_text() == "someone edited this\n"


# ---- the HTTP approval gate ------------------------------------------------------------------

@pytest.fixture
def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def save(changes):
    return store.save("repo_x", {"summary": "s", "changes": changes}, {"verdict": "approve"})


async def test_apply_endpoint_flow(root, client, monkeypatch):
    monkeypatch.setattr(api_mod, "get_root", lambda repo_id: str(root))
    pid = save([change(), change(path="../evil.py")])
    async with client as c:
        info = (await c.get(f"/api/proposals/{pid}")).json()
        assert info["can_apply"] and info["changes"][0]["eligible"] and "old" not in info["changes"][0]

        res = (await c.post(f"/api/proposals/{pid}/apply", json={"change_indexes": [0, 1, 9]})).json()["results"]
        assert [r["status"] for r in res] == ["applied", "skipped", "skipped"]
        assert "inside the repository" in res[1]["detail"]  # traversal blocked

        again = (await c.post(f"/api/proposals/{pid}/apply", json={"change_indexes": [0]})).json()["results"]
        assert again[0]["detail"] == "already applied"
        assert (await c.get(f"/api/proposals/{pid}")).json()["changes"][0]["applied"] is True

        undo = (await c.post(f"/api/proposals/{pid}/undo")).json()["results"]
        assert undo[0]["status"] == "undone" and b"'v': 1" not in (root / "app/main.py").read_bytes()


async def test_endpoints_refuse_without_root_or_unknown_id(client, monkeypatch):
    monkeypatch.setattr(api_mod, "get_root", lambda repo_id: None)
    pid = save([change()])
    async with client as c:
        assert (await c.post(f"/api/proposals/{pid}/apply", json={"change_indexes": [0]})).status_code == 409
        assert (await c.get("/api/proposals/nope")).status_code == 404
        assert (await c.post(f"/api/proposals/{pid}/apply", json={"change_indexes": []})).status_code == 422