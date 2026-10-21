import time

from smart_car_decision.web_video import AnnotatedFrameStore, should_release_camera_for_mode


def test_annotated_frame_store_returns_recent_jpeg_frame():
    store = AnnotatedFrameStore(max_age_sec=1.0)
    store.update(b"jpeg-data", now=10.0)

    assert store.latest(now=10.5) == b"jpeg-data"


def test_annotated_frame_store_rejects_stale_or_empty_frames():
    store = AnnotatedFrameStore(max_age_sec=0.5)
    store.update(b"jpeg-data", now=10.0)
    assert store.latest(now=10.6) is None

    store.update(b"", now=time.monotonic())
    assert store.latest() is None


def test_annotated_frame_store_waits_for_new_frame_version():
    store = AnnotatedFrameStore(max_age_sec=1.0)

    frame, version = store.wait_for_frame(last_version=0, timeout=0.0, now=10.0)
    assert frame is None
    assert version == 0

    store.update(b"fresh-jpeg", now=10.0)

    frame, version = store.wait_for_frame(last_version=0, timeout=0.0, now=10.1)
    assert frame == b"fresh-jpeg"
    assert version == 1

    # A slow detector must not retransmit the same JPEG on every stream timeout.
    frame, version = store.wait_for_frame(last_version=1, timeout=0.0, now=10.2)
    assert frame is None
    assert version == 1


def test_visual_modes_release_direct_camera_preview():
    assert should_release_camera_for_mode("auto") is True
    assert should_release_camera_for_mode("object_follow") is True
    assert should_release_camera_for_mode("manual") is False


def test_snapshot_has_sequence_and_rejects_old_annotated_frame(monkeypatch):
    monkeypatch.setattr("smart_car_decision.web_video.time.monotonic", lambda: 10.1)
    store = AnnotatedFrameStore(max_age_sec=1.5)
    store.update(b"annotated", now=10.0)
    snapshot = store.snapshot()
    assert snapshot["sequence"] == 1
    assert snapshot["jpeg"] == b"annotated"
    assert snapshot["age_ms"] == 100
    monkeypatch.setattr("smart_car_decision.web_video.time.monotonic", lambda: 10.6)
    assert store.snapshot() is None
