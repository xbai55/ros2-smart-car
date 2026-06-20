from pathlib import Path

from smart_car_decision.web_static import resolve_static_dir


def test_resolve_static_dir_prefers_configured_dist(tmp_path):
    dist = tmp_path / "web-console" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<div id='root'></div>", encoding="utf-8")

    resolved = resolve_static_dir(str(dist), Path("/old/static"))

    assert resolved == dist
