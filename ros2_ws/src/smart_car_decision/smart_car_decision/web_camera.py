import time


class CameraStream:
    blocked_modes = {"auto", "object_follow", "color_track"}

    def __init__(self, source, cv2_module, mode_provider, capture_fps=None, target_fps=None):
        self.source = source
        self.cv2 = cv2_module
        self.mode_provider = mode_provider
        self.capture_fps = None if capture_fps is None else float(capture_fps)
        self.target_fps = None if target_fps is None else float(target_fps)
        self.capture = None
        self.last_open_attempt = 0.0

    def is_blocked_by_mode(self):
        return self.mode_provider() in self.blocked_modes

    def open(self):
        if self.is_blocked_by_mode():
            self.close()
            return False
        if self.capture is not None and self.capture.isOpened():
            return True
        if time.monotonic() - self.last_open_attempt < 1.0:
            return False
        self.last_open_attempt = time.monotonic()
        try:
            parsed = int(self.source)
        except ValueError:
            parsed = self.source
        self.capture = self.cv2.VideoCapture(parsed)
        if self.capture_fps is not None and self.capture_fps > 0:
            self.capture.set(self.cv2.CAP_PROP_FPS, self.capture_fps)
        return self.capture.isOpened()

    def frames(self):
        try:
            while True:
                if not self.open():
                    return
                ok, frame = self.capture.read()
                if not ok:
                    self.close()
                    return
                ok, encoded = self.cv2.imencode(".jpg", frame)
                if not ok:
                    continue
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + encoded.tobytes()
                    + b"\r\n"
                )
        finally:
            self.close()

    def close(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None
