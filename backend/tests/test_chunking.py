from app.rag.chunking import CHUNK_LINES, chunk_repo, chunk_text


def test_short_file_is_one_chunk():
    chunks = chunk_text("a.py", "x = 1\ny = 2\n")
    assert len(chunks) == 1 and chunks[0].start_line == 1 and chunks[0].end_line == 2


def test_long_file_overlaps_and_covers_everything():
    text = "\n".join(f"line{i}" for i in range(1, 151))
    chunks = chunk_text("a.py", text)
    assert chunks[0].end_line == CHUNK_LINES
    assert chunks[1].start_line < chunks[0].end_line  # overlap
    assert chunks[-1].end_line == 150


def test_blank_file_skipped():
    assert chunk_text("a.py", "\n\n  \n") == []


def test_repo_walk_skips_junk(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("var a = 1;\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    paths = {c.path for c in chunk_repo(tmp_path)}
    assert paths == {"src/app.py"}


def test_leading_blank_lines_keep_real_line_numbers():
    chunks = chunk_text("a.py", "\n\nx = 1\ny = 2\n")
    assert chunks[0].start_line == 3 and chunks[0].text.startswith("x = 1")


def test_empty_repo_is_rejected_not_indexed(tmp_path):
    import pytest

    from app.rag.ingestion import index_repo

    (tmp_path / "README").write_text("extensionless files are skipped\n")
    with pytest.raises(ValueError, match="No indexable files"):
        index_repo("empty-test", path=str(tmp_path))