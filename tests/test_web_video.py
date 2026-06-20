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


def test_visual_modes_release_direct_camera_preview():
    assert should_release_camera_for_mode("auto") is True
    assert should_release_camera_for_mode("object_follow") is True
    assert should_release_camera_for_mode("manual") is False
