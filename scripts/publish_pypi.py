#!/usr/bin/env python3
"""Safe-ish PyPI publish helper for the SoroPy package.

Can be run from the repository root or from the soropy/ package folder.
Does not change the package name; name always comes from pyproject.toml.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import List, Optional, Sequence

VERSION_RE = re.compile(r'(?m)^version\s*=\s*["\']([^"\']+)["\']')
SETUP_VERSION_RE = re.compile(r'(?m)^(version\s*=\s*)["\'][^"\']+["\']')
INIT_VERSION_RE = re.compile(r'(?m)^(__version__\s*=\s*)["\'][^"\']+["\']')

REQUIRED_SDIST_FILES = (
    "examples/websocket/README.md",
    "examples/websocket/group_moderator.py",
    "examples/websocket/ai_assistant.py",
    "examples/websocket/capability_cookbook.py",
    "examples/websocket/support_desk_bot.py",
    "examples/websocket/campaign_broadcaster.py",
    "examples/websocket/event_audit_logger.py",
    "examples/websocket/send_file_interactive.py",
)


def find_package_root(start: Optional[Path] = None) -> Path:
    """Locate the directory that contains the package pyproject.toml."""
    here = (start or Path.cwd()).resolve()
    candidates = [here, here / "soropy"]
    # Also walk up a few parents for convenience.
    parent = here
    for _ in range(4):
        candidates.append(parent)
        candidates.append(parent / "soropy")
        parent = parent.parent

    seen = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        pyproject = candidate / "pyproject.toml"
        if not pyproject.is_file():
            continue
        text = pyproject.read_text(encoding="utf-8")
        if 'name = "soropy"' in text or "name = 'soropy'" in text:
            return candidate
    raise SystemExit(
        "Could not find package root with pyproject.toml (name = \"soropy\")."
    )


def read_version(pyproject: Path) -> str:
    text = pyproject.read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if not match:
        raise SystemExit(f"version not found in {pyproject}")
    return match.group(1)


def sync_version(package_root: Path, version: str) -> None:
    setup_py = package_root / "setup.py"
    if setup_py.is_file():
        text = setup_py.read_text(encoding="utf-8")
        updated, count = SETUP_VERSION_RE.subn(rf'\1"{version}"', text, count=1)
        if count:
            setup_py.write_text(updated, encoding="utf-8")
            print(f"synced setup.py → {version}")
        else:
            print("warning: setup.py version pattern not found")

    init_py = package_root / "soropy" / "__init__.py"
    if init_py.is_file():
        text = init_py.read_text(encoding="utf-8")
        updated, count = INIT_VERSION_RE.subn(rf'\1"{version}"', text, count=1)
        if count:
            init_py.write_text(updated, encoding="utf-8")
            print(f"synced soropy/__init__.py → {version}")
        else:
            print("warning: __init__.py __version__ pattern not found")


def compare_readmes(package_root: Path) -> None:
    package_readme = package_root / "README.md"
    root_readme = package_root.parent / "README.md"
    if package_readme.is_file() and root_readme.is_file():
        if package_readme.read_bytes() != root_readme.read_bytes():
            raise SystemExit(
                "README.md and soropy/README.md differ (byte-for-byte). "
                "Keep them identical before publishing."
            )
        print("README.md files are byte-for-byte identical.")
    else:
        print("README pair check skipped (one of the files is missing).")


def clean_artifacts(package_root: Path) -> None:
    for name in ("dist", "build"):
        path = package_root / name
        if path.exists():
            shutil.rmtree(path)
            print(f"removed {path}")
    for egg in package_root.glob("*.egg-info"):
        shutil.rmtree(egg)
        print(f"removed {egg}")
    for egg in package_root.glob("**/*.egg-info"):
        if egg.is_dir():
            shutil.rmtree(egg)
            print(f"removed {egg}")


def run(cmd: Sequence[str], cwd: Path) -> None:
    print("+", " ".join(cmd))
    result = subprocess.run(list(cmd), cwd=str(cwd))
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def run_tests(package_root: Path, repo_root: Path) -> None:
    # Prefer running from package root so `examples` and `tests` resolve.
    compile_targets = ["soropy", "examples", "tests"]
    existing = [t for t in compile_targets if (package_root / t).exists()]
    if existing:
        run([sys.executable, "-m", "compileall", "-q", *existing], cwd=package_root)
    run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=package_root)
    ruff_targets = [
        "examples/websocket",
        "tests/test_websocket_examples.py",
    ]
    existing_ruff = [t for t in ruff_targets if (package_root / t).exists()]
    if existing_ruff:
        run([sys.executable, "-m", "ruff", "check", *existing_ruff], cwd=package_root)


def build_package(package_root: Path) -> List[Path]:
    run([sys.executable, "-m", "build"], cwd=package_root)
    dist_dir = package_root / "dist"
    files = sorted(dist_dir.glob("*"))
    if not files:
        raise SystemExit("dist/ is empty after build")
    return files


def twine_check(package_root: Path, dist_files: Sequence[Path]) -> None:
    # Important: do not pass shell wildcards to subprocess list form.
    paths = [str(path) for path in dist_files]
    run([sys.executable, "-m", "twine", "check", *paths], cwd=package_root)


def verify_sdist(dist_files: Sequence[Path], version: str) -> None:
    sdist = None
    for path in dist_files:
        if path.name.endswith(".tar.gz"):
            sdist = path
            break
    if sdist is None:
        raise SystemExit("sdist .tar.gz not found in dist/")

    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()

    # sdist members are typically prefixed with soropy-<version>/
    prefix_candidates = [f"soropy-{version}/", ""]
    missing: List[str] = []
    for required in REQUIRED_SDIST_FILES:
        found = False
        for prefix in prefix_candidates:
            needle = prefix + required
            if any(name == needle or name.endswith("/" + required) for name in names):
                found = True
                break
        if not found:
            missing.append(required)
    if missing:
        raise SystemExit(
            "sdist is missing required files:\n  - " + "\n  - ".join(missing)
        )
    print("sdist contains required websocket example files.")


def upload(package_root: Path, dist_files: Sequence[Path]) -> None:
    answer = input("Type YES to upload to PyPI: ").strip()
    if answer != "YES":
        raise SystemExit("Upload cancelled (expected exact YES).")
    paths = [str(path) for path in dist_files]
    run([sys.executable, "-m", "twine", "upload", *paths], cwd=package_root)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and publish SoroPy to PyPI.")
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Only build and check; do not upload.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip compileall/pytest/ruff steps.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    package_root = find_package_root()
    repo_root = package_root.parent if (package_root.parent / "README.md").is_file() else package_root
    pyproject = package_root / "pyproject.toml"
    version = read_version(pyproject)
    print(f"package root: {package_root}")
    print(f"version: {version}")
    print("package name remains: soropy (from pyproject.toml)")
    print('optional extra remains: pip install "soropy[ws]"')

    sync_version(package_root, version)
    compare_readmes(package_root)
    clean_artifacts(package_root)

    if not args.skip_tests:
        run_tests(package_root, repo_root)
    else:
        print("tests skipped (--skip-tests)")

    dist_files = build_package(package_root)
    twine_check(package_root, dist_files)
    verify_sdist(dist_files, version)

    print("Artifacts:")
    for path in dist_files:
        print(f"  {path}")

    if args.no_upload:
        print("--no-upload set; build/check complete.")
        return 0

    upload(package_root, dist_files)
    print("Upload finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
