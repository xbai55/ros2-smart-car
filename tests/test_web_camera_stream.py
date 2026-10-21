import time

import pytest

from smart_car_decision.web_camera import CameraStream


class FakeFrame:
    shape = (720, 1280, 3)

    def __init__(self, number):
        self.number = number


class EncodedFrame:
    def __init__(self, frame):
        self.frame = frame

    def tobytes(self):
        return str(self.frame.number).encode()


class FakeCapture:
    def __init__(self):
        self.read_count = 0
        self.released = False
        self.settings = []
        self.reading = False
        self.delay = 0.005
        self.failed = False

    def isOpened(self):
        return not self.released and not self.failed

    def read(self):
        self.reading = True
        time.sleep(self.delay)
        self.read_count += 1
        self.reading = False
        return not self.failed, FakeFrame(self.read_count)

    def release(self):
        assert not self.reading, "capture must never be released during read"
        self.released = True

    def set(self, prop, value):
        self.settings.append((prop, value))


class FakeCv2:
    CAP_PROP_FPS, CAP_V4L2, CAP_PROP_FOURCC = 5, 200, 6
    CAP_PROP_FRAME_WIDTH, CAP_PROP_FRAME_HEIGHT, CAP_PROP_BUFFERSIZE = 3, 4, 38
    IMWRITE_JPEG_QUALITY, INTER_AREA = 1, 3

    def __init__(self):
        self.capture = FakeCapture()
        self.sources, self.encodes, self.resizes = [], [], []

    def VideoCapture(self, source, backend=None):
        self.sources.append((source, backend))
        return self.capture

    @staticmethod
    def VideoWriter_fourcc(*chars):
        return "".join(chars)

    def imencode(self, suffix, frame, params):
        self.encodes.append(params)
        return True, EncodedFrame(frame)

    def resize(self, frame, size, interpolation):
        self.resizes.append(size)
        return frame


@pytest.fixture
def make_stream(monkeypatch):
    monkeypatch.setattr("smart_car_decision.web_camera.sys.platform", "linux")
    streams = []
    def make(source="0", mode=lambda: "stop", **kwargs):
        cv2 = FakeCv2()
        stream = CameraStream(source, cv2, mode, **kwargs)
        streams.append(stream)
        return stream, cv2
    yield make
    for stream in streams:
        stream.close()


def test_camera_uses_v4l2_mjpg_small_buffer_and_bounded_jpeg(make_stream):
    stream, cv2 = make_stream(capture_fps=30)
    assert stream.open()
    assert cv2.sources == [(0, cv2.CAP_V4L2)]
    assert cv2.capture.settings == [(6, "MJPG"), (3, 1280), (4, 720), (5, 30), (38, 1)]
    assert cv2.encodes[0] == [cv2.IMWRITE_JPEG_QUALITY, 75]
    assert cv2.resizes[0] == (960, 540)


def test_stable_device_symlink_receives_v4l2_and_format_settings(make_stream, monkeypatch):
    monkeypatch.setattr("smart_car_decision.web_camera.os.path.realpath", lambda _: "/dev/video0")
    stream, cv2 = make_stream("/dev/camera_depth")
    assert stream.open()
    assert cv2.sources == [("/dev/camera_depth", cv2.CAP_V4L2)]
    assert (6, "MJPG") in cv2.capture.settings


def test_slow_consumer_skips_old_frames_while_capture_keeps_draining(make_stream):
    stream, cv2 = make_stream(target_fps=40)
    frames = stream.frames()
    first = next(frames)
    initial = stream.diagnostics()
    time.sleep(0.16)  # Simulate network backpressure without requesting a frame.
    later = stream.diagnostics()
    second = next(frames)
    assert later["frames_read"] > initial["frames_read"] + 5
    assert later["sequence"] > initial["sequence"] + 2
    assert first != second
    assert later["frames_read"] > later["frames_encoded"]
    frames.close()


def test_concurrent_clients_share_one_capture_and_do_not_release_each_other(make_stream):
    stream, cv2 = make_stream(target_fps=10)
    first, second = stream.frames(), stream.frames()
    assert next(first) == next(second)
    assert len(cv2.sources) == 1
    first.close()
    assert not cv2.capture.released
    assert next(second)
    second.close()
    stream.close()
    assert cv2.capture.released


def test_close_never_releases_during_capture_read(make_stream):
    stream, cv2 = make_stream()
    cv2.capture.delay = 0.03
    assert stream.open()
    deadline = time.monotonic() + 0.2
    while not cv2.capture.reading and time.monotonic() < deadline:
        time.sleep(0.001)
    stream.close()
    assert cv2.capture.released
    assert stream.diagnostics()["running"] is False


def test_no_viewers_releases_camera_after_idle_timeout(make_stream):
    stream, cv2 = make_stream(idle_timeout=0.03)
    assert stream.frame_snapshot()
    deadline = time.monotonic() + 0.5
    while not cv2.capture.released and time.monotonic() < deadline:
        time.sleep(0.01)
    assert cv2.capture.released


def test_vision_mode_blocks_capture_and_rejects_previous_frame(make_stream):
    mode = ["stop"]
    stream, cv2 = make_stream(mode=lambda: mode[0])
    assert stream.open()
    mode[0] = "object_follow"
    assert stream.frame_snapshot() is None
    stream.close()
    assert cv2.capture.released


def test_vision_mode_never_opens_camera(make_stream):
    stream, cv2 = make_stream(mode=lambda: "color_track")
    assert stream.open() is False
    assert cv2.sources == []


def test_network_source_keeps_default_backend(make_stream):
    stream, cv2 = make_stream("rtsp://camera/stream")
    assert stream.open()
    assert cv2.sources == [("rtsp://camera/stream", None)]
    assert cv2.capture.settings == [(38, 1)]


def test_capture_failure_is_reported_and_releases_device(make_stream):
    stream, cv2 = make_stream()
    cv2.capture.failed = True
    assert stream.open() is False
    assert cv2.capture.released
    assert stream.diagnostics()["error"] == "camera_open_failed"


def test_expired_frame_is_not_returned_as_live(make_stream):
    stream, cv2 = make_stream()
    cv2.capture.delay = 0.1
    assert stream.open()
    with stream._condition:
        stream._captured_at -= 2
    assert stream.frame_snapshot(timeout=0) is None
