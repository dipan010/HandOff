"""Keep HandOff's code, UI text and docs free of buzzwords.

We describe what the assistant does in plain words ("steps", "check",
"remember"). This test fails if any of the words below creep back in.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Folders and files that HandOff owns and ships.
CHECKED_PATHS = [
    "backend/app",
    "backend/tests",
    "extension",
    "frontend/src",
    "desktop",
    "docs",
    "README.md",
    "HandOff.md",
]

CHECKED_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".css", ".html", ".md", ".json"}
SKIPPED_DIRS = {"node_modules", "__pycache__", ".next", "dist", "venv"}

# Short forms are matched with exact case so normal words ("drag") pass.
EXACT_CASE = ["ACI", "RAG", "LLM", "LLMs", "SPAV"]
ANY_CASE = [
    "agentic",
    "orchestrator",
    "orchestration",
    "leverage",
    "leveraging",
    "perception",
    "milestone",
    "milestones",
    "sub-agent",
    "sub-agents",
    "subagent",
    "subagents",
    "AI-powered",
    "seamless",
    "seamlessly",
    "cutting-edge",
]

_exact = re.compile(r"\b(" + "|".join(map(re.escape, EXACT_CASE)) + r")\b")
_any = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, ANY_CASE)) + r")(?![\w-])", re.IGNORECASE)


def _files():
    this_file = Path(__file__).resolve()
    for rel in CHECKED_PATHS:
        path = REPO / rel
        if path.is_file():
            yield path
        elif path.is_dir():
            for f in path.rglob("*"):
                if (
                    f.is_file()
                    and f.suffix in CHECKED_SUFFIXES
                    and not SKIPPED_DIRS.intersection(f.parts)
                    and f.resolve() != this_file
                ):
                    yield f


def test_no_banned_words():
    hits = []
    for f in _files():
        text = f.read_text(encoding="utf-8", errors="ignore")
        for n, line in enumerate(text.splitlines(), 1):
            for m in list(_exact.finditer(line)) + list(_any.finditer(line)):
                hits.append(f"{f.relative_to(REPO)}:{n}: '{m.group(0)}'")
    assert not hits, "Replace these with plain words:\n" + "\n".join(hits)


def test_checker_catches_examples():
    assert _any.search("An AI-powered helper")
    assert _any.search("the Orchestrator runs")
    assert _exact.search("send it to the LLM")
    assert not _exact.search("drag the slider")
    assert not _any.search("plain steps and checks")
