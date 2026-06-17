import threading
import time


CAMERA_OWNER_MODES = {"auto", "object_follow", "color_track"}


def should_release_camera_for_mode(mode):
    return str(mode).strip().lower() in CAMERA_OWNER_MODES


class AnnotatedFrameStore:
    def __init__(self, max_age_sec=1.0):
        self.max_age_sec = float(max_age_sec)
        self._lock = threading.Lock()
        self._frame = None
        self._updated_at = 0.0

    def update(self, frame, now=None):
        with self._lock:
            self._frame = bytes(frame) if frame else None
            self._updated_at = time.monotonic() if now is None else float(now)

    def latest(self, now=None):
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            if not self._frame:
                return None
            if now - self._updated_at > self.max_age_sec:
                return None
            return self._frame
