import pytest

from smart_car_decision.web_camera import CameraStream


class EncodedFrame:
    def tobytes(self):
        return b"jpeg-frame"


class FakeCapture:
    def __init__(self):
        self.read_count = 0
        self.released = False
        self.settings = []

    def isOpened(self):
        return not self.released

    def read(self):
        self.read_count += 1
        if self.read_count == 1:
            return True, object()
        return False, None

    def release(self):
        self.released = True

    def set(self, prop, value):
        self.settings.append((prop, value))


class FakeCv2:
    CAP_PROP_FPS = 5

    def __init__(self):
        self.capture = FakeCapture()
        self.sources = []

    def VideoCapture(self, source):
        self.sources.append(source)
        return self.capture

    def imencode(self, suffix, frame):
        return True, EncodedFrame()


def test_camera_stream_uses_known_working_synchronous_capture_without_tuning():
    cv2 = FakeCv2()
    stream = CameraStream("0", cv2, lambda: "stop")

    frames = stream.frames()
    chunk = next(frames)

    assert cv2.sources == [0]
    assert cv2.capture.settings == []
    assert b"jpeg-frame" in chunk

    with pytest.raises(StopIteration):
        next(frames)
    assert cv2.capture.released is True


def test_camera_stream_does_not_open_device_in_vision_modes():
    cv2 = FakeCv2()
    stream = CameraStream("0", cv2, lambda: "object_follow")

    assert stream.open() is False
    assert cv2.sources == []


def test_camera_stream_applies_configured_capture_fps():
    cv2 = FakeCv2()
    stream = CameraStream("0", cv2, lambda: "stop", capture_fps=30.0, target_fps=20.0)

    frames = stream.frames()
    next(frames)

    assert cv2.capture.settings == [(cv2.CAP_PROP_FPS, 30.0)]
