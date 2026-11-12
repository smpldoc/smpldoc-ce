"""Repository hygiene checks that keep this project safe to trust.

Standard library only, so it runs anywhere:
    python scripts/check_repo.py
Exit code 1 lists every problem found. These rules exist so that anyone can see
the project is not pulling in floating code, leaking secrets or running
untrusted input in CI.
"""
import re
import sys
from pathlib import Path

REQUIRED_FILES = (
    "LICENSE", "README.md", "SECURITY.md", "CHANGELOG.md", "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md", ".github/dependabot.yml",
)

USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.MULTILINE)
FULL_SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
DOCKER_DIGEST = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")
TOP_LEVEL_PERMISSIONS = re.compile(r"^permissions:", re.MULTILINE)
PULL_REQUEST_TARGET = re.compile(r"^\s*pull_request_target\b", re.MULTILINE)
PIPE_TO_SHELL = re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b")
FROM = re.compile(r"^\s*FROM\s+(?:--\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", re.IGNORECASE | re.MULTILINE)
SECRET_SHAPES = {
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", ".data"}


def check_pins(text: str, filename: str) -> list[str]:
    errors = []
    for ref in USES.findall(text):
        if ref.startswith("./"):
            continue
        ok = DOCKER_DIGEST.match(ref) if ref.startswith("docker://") else FULL_SHA.match(ref)
        if not ok:
            errors.append(f"{filename}: {ref} is not pinned to a full commit SHA or image digest")
    return errors


def check_permissions(text: str, filename: str) -> list[str]:
    if TOP_LEVEL_PERMISSIONS.search(text):
        return []
    return [f"{filename}: missing top-level permissions (default to read-only)"]


def check_triggers(text: str, filename: str) -> list[str]:
    if PULL_REQUEST_TARGET.search(text):
        return [f"{filename}: pull_request_target runs untrusted code with secrets; do not use it"]
    return []


def check_pipe_to_shell(text: str, filename: str) -> list[str]:
    return [f"{filename}: downloads and runs a script in one step; download, verify, then run"
            for _ in PIPE_TO_SHELL.findall(text)]


def check_secrets(text: str, filename: str) -> list[str]:
    return [f"{filename}: looks like a {label}" for label, shape in SECRET_SHAPES.items() if shape.search(text)]


def check_dockerfile(text: str, filename: str) -> list[str]:
    errors, stages = [], set()
    for image, stage in FROM.findall(text):
        if image != "scratch" and image not in stages and "@sha256:" not in image:
            errors.append(f"{filename}: base image {image} is not pinned by digest")
        if stage:
            stages.add(stage)
    return errors


def check_required_files(root: Path) -> list[str]:
    return [f"missing required file {name}" for name in REQUIRED_FILES if not (root / name).is_file()]


def tracked_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS))


def run(root: Path) -> list[str]:
    errors = check_required_files(root)
    for path in tracked_files(root):
        name = str(path.relative_to(root))
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary files cannot hold the text shapes we look for
        errors += check_secrets(text, name)
        if path.parent == root / ".github" / "workflows" and path.suffix in {".yml", ".yaml"}:
            for check in (check_pins, check_permissions, check_triggers, check_pipe_to_shell):
                errors += check(text, name)
        if path.name == "Dockerfile" or path.name.startswith("Dockerfile."):
            errors += check_dockerfile(text, name)
    return errors


if __name__ == "__main__":
    problems = run(Path(__file__).resolve().parent.parent)
    for problem in problems:
        print(f"::error::{problem}")
    sys.exit(1 if problems else 0)
