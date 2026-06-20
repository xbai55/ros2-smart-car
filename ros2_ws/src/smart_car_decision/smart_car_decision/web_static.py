from pathlib import Path


def resolve_static_dir(configured_dir, package_static_dir):
    configured = str(configured_dir or "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate
    return Path(package_static_dir)
