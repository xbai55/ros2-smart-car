import threading
import time


CAMERA_OWNER_MODES = {"auto", "object_follow", "color_track"}


def should_release_camera_for_mode(mode):
    return str(mode).strip().lower() in CAMERA_OWNER_MODES


class AnnotatedFrameStore:
    def __init__(self, max_age_sec=1.0):
        self.max_age_sec = float(max_age_sec)
        self._condition = threading.Condition()
        self._frame = None
        self._updated_at = 0.0
        self._version = 0

    def update(self, frame, now=None):
        with self._condition:
            self._frame = bytes(frame) if frame else None
            self._updated_at = time.monotonic() if now is None else float(now)
            self._version += 1
            self._condition.notify_all()

    def latest(self, now=None):
        now = time.monotonic() if now is None else float(now)
        with self._condition:
            if not self._frame:
                return None
            if now - self._updated_at > self.max_age_sec:
                return None
            return self._frame

    def wait_for_frame(self, last_version=0, timeout=0.1, now=None):
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while self._version <= last_version:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            now = time.monotonic() if now is None else float(now)
            if not self._frame or now - self._updated_at > self.max_age_sec:
                return None, self._version
            return self._frame, self._version
