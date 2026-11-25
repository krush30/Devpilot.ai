"""Tester agent: writes pytest tests for a change that has been applied to a sandbox copy.

Not part of the main graph. It runs only when the user presses "Run tests in sandbox",
because it ends in executing AI-written code (inside Docker, never on the host).
"""
import ast
from pathlib import Path

from app.agents.base import ask
from app.llm.router import AllProvidersFailed
from app.llm.utils import extract_json
from app.sandbox.workspace import list_python_files

TEST_FILE = "test_devpilot_generated.py"
FORBIDDEN_IMPORTS = {"subprocess", "ctypes", "pty", "socket", "ftplib", "smtplib", "telnetlib", "multiprocessing"}
FORBIDDEN_NAMES = {"eval", "exec", "__import__"}
FORBIDDEN_OS_CALLS = {"system", "popen", "execv", "execl", "execvp", "spawnl", "spawnv", "fork", "kill"}

SYSTEM = """You are the Tester in a team of software engineering agents.
You write pytest tests for a code change that has been applied to a copy of the repository.
Reply with JSON only, in exactly this shape:
{"notes": "one or two sentences on what the tests cover",
 "content": "the full contents of the test file"}
Rules:
- Use pytest. The repository root is on sys.path; import modules exactly as the project does.
- Test the behaviour added or changed by the diff, including at least one edge case.
- Tests must be self-contained and deterministic: no network, no subprocesses, no sockets, no sleeping,
  no real API keys. Use tmp_path for files and monkeypatch to fake external services.
- Keep it under 120 lines. Never modify project files.
- If the change cannot be tested without unavailable services, test the smallest pure-logic part you can."""


class GenerationError(Exception):
    """The tests could not be produced. The message is user-safe."""


def check_test_code(code: str) -> str | None:
    """Defence in depth before running generated code (Docker is the real isolation)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"the test file has a syntax error (line {e.lineno})"
    if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
               for n in ast.walk(tree)):
        return "the test file contains no test_ functions"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    return f"importing '{alias.name}' is not allowed in generated tests"
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in FORBIDDEN_IMPORTS:
            return f"importing from '{node.module}' is not allowed in generated tests"
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in FORBIDDEN_NAMES:
                return f"calling {f.id}() is not allowed in generated tests"
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "os" \
                    and f.attr in FORBIDDEN_OS_CALLS:
                return f"calling os.{f.attr}() is not allowed in generated tests"
    return None


def _file_excerpt(ws: Path, rel: str) -> str:
    target = ws / rel
    if not target.is_file():
        return ""
    return "\n".join(target.read_text(encoding="utf-8", errors="replace").splitlines()[:300])


async def generate_tests(summary: str, changes: list[dict], ws: Path) -> dict:
    parts = [
        f"### {c['path']} ({c['action']})\nWhy: {c['explanation']}\nDiff:\n{c['diff']}\n\n"
        f"File after the change:\n{_file_excerpt(ws, c['path'])}"
        for c in changes[:3]
    ]
    user = (f"Change summary: {summary}\n\nPython files in the repository:\n" + "\n".join(list_python_files(ws))
            + "\n\n" + "\n\n".join(parts))
    last = ""
    for _ in range(2):  # one retry for malformed or unsafe output
        try:
            text, provider = await ask([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
            data = extract_json(text)
            content = str(data.get("content", ""))
            problem = check_test_code(content)
            if problem:
                raise ValueError(problem)
            return {"content": content, "notes": str(data.get("notes", "")), "provider": provider}
        except AllProvidersFailed as e:
            raise GenerationError(f"No model provider available: {e}")
        except Exception as e:
            last = str(e)
            user += f"\n\nYour previous reply was rejected: {e}. Reply with valid JSON containing safe test code."
    raise GenerationError(f"Could not produce valid tests: {last}")