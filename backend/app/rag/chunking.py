"""Walk a repository and split source files into overlapping line-based chunks."""
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", ".next", ".venv", "venv", "__pycache__", "dist",
    "build", "chroma_data", ".idea", ".vscode", "target", "coverage",
}
CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".c", ".h",
    ".cpp", ".cs", ".rb", ".php", ".sql", ".sh", ".yml", ".yaml", ".toml",
    ".json", ".md", ".html", ".css", ".txt",
}
SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}
MAX_FILE_BYTES = 200_000
CHUNK_LINES = 60
OVERLAP_LINES = 10


@dataclass
class Chunk:
    path: str  # relative to repo root, forward slashes
    start_line: int  # 1-based, inclusive
    end_line: int
    text: str


def iter_source_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if p.suffix.lower() not in CODE_EXTS or p.name in SKIP_FILES:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield p


def chunk_text(rel_path: str, text: str) -> list[Chunk]:
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        return []
    step = CHUNK_LINES - OVERLAP_LINES
    chunks = []
    for start in range(0, len(lines), step):
        window = lines[start:start + CHUNK_LINES]
        # Trim leading blank lines but keep start_line accurate, so line numbers stay real.
        lead = 0
        while lead < len(window) and not window[lead].strip():
            lead += 1
        body = "\n".join(window[lead:]).rstrip()
        if body:
            chunks.append(Chunk(rel_path, start + 1 + lead, start + len(window), body))
        if start + CHUNK_LINES >= len(lines):
            break
    return chunks


def chunk_repo(root: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for p in iter_source_files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable
        rel = p.relative_to(root).as_posix()
        chunks.extend(chunk_text(rel, text))
    return chunks