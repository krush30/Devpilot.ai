import sys

import pytest

from app.sandbox import workspace as w
from app.tools.apply import apply_change


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_bytes(b"def f():\r\n    return 1\r\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_x():\n    pass\n")
    (root / ".env").write_text("GROQ_API_KEY=supersecret\n")
    (root / ".env.local").write_text("X=1\n")
    (root / "server.pem").write_text("-----BEGIN-----\n")
    (root / "id_rsa").write_text("key")
    (root / "data.db").write_bytes(b"sqlite")
    for junk in (".git", "node_modules", ".venv", "chroma_data"):
        (root / junk).mkdir()
        (root / junk / "x.py").write_text("junk = 1\n")
    (root / "big.txt").write_bytes(b"x" * (w.MAX_FILE_BYTES + 1))
    return root


def names(ws):
    return {p.relative_to(ws).as_posix() for p in ws.rglob("*") if p.is_file()}


def test_copy_includes_code_and_excludes_secrets_and_junk(project):
    ws = w.make_workspace(project)
    try:
        assert names(ws) == {"app/main.py", "tests/test_x.py"}
        assert not any("secret" in p.read_text(errors="ignore") for p in ws.rglob("*") if p.is_file())
    finally:
        w.cleanup(ws)
    assert not ws.exists()


def test_changes_applied_to_the_copy_never_touch_the_original(project):
    original = (project / "app" / "main.py").read_bytes()
    ws = w.make_workspace(project)
    try:
        change = {"path": "app/main.py", "action": "modify", "old": "def f():\n    return 1",
                  "new": "def f():\n    return 2", "syntax": "ok"}
        assert apply_change(ws, change).status == "applied"
        assert b"return 2" in (ws / "app" / "main.py").read_bytes()
    finally:
        w.cleanup(ws)
    assert (project / "app" / "main.py").read_bytes() == original


def test_too_large_projects_are_refused(project, monkeypatch):
    monkeypatch.setattr(w, "MAX_FILES", 1)
    with pytest.raises(w.WorkspaceTooLarge, match="too large"):
        w.make_workspace(project)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_symlinks_are_not_followed(project, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    (project / "app" / "link.py").symlink_to(outside)
    (project / "linkdir").symlink_to(tmp_path)
    ws = w.make_workspace(project)
    try:
        assert "app/link.py" not in names(ws) and not (ws / "linkdir").exists()
    finally:
        w.cleanup(ws)


def test_python_file_listing(project):
    ws = w.make_workspace(project)
    try:
        assert w.list_python_files(ws) == ["app/main.py", "tests/test_x.py"]
    finally:
        w.cleanup(ws)