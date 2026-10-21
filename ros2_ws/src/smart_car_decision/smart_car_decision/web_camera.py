import os
import sys
import threading
import time


class CameraStream:
    """Continuously drain capture; share one newest JPEG without a frame queue."""

    blocked_modes = {"auto", "object_follow", "color_track"}

    def __init__(self, source, cv2_module, mode_provider, capture_fps=None, target_fps=12,
                 camera_fourcc="MJPG", camera_width=1280, camera_height=720,
                 jpeg_quality=75, stream_width=960, idle_timeout=2.0):
        self.source = str(source)
        self.cv2 = cv2_module
        self.mode_provider = mode_provider
        self.capture_fps = float(capture_fps or 0)
        self.target_fps = max(1.0, float(target_fps or 12))
        self.camera_fourcc = str(camera_fourcc).strip()
        self.camera_width = int(camera_width)
        self.camera_height = int(camera_height)
        self.jpeg_quality = max(30, min(95, int(jpeg_quality)))
        self.stream_width = max(0, int(stream_width))
        self.idle_timeout = max(0.1, float(idle_timeout))
        self.capture = None
        self.last_open_attempt = 0.0
        self._condition = threading.Condition(threading.RLock())
        self._worker = None
        self._stop = threading.Event()
        self._clients = 0
        self._last_access = 0.0
        self._jpeg = None
        self._sequence = 0
        self._captured_at = 0.0
        self._wall_time = 0.0
        self._frames_read = 0
        self._frames_encoded = 0
        self._error = None

    def is_blocked_by_mode(self):
        return self.mode_provider() in self.blocked_modes

    def _open_capture(self):
        try:
            parsed = int(self.source)
        except ValueError:
            parsed = self.source
        # Stable /dev/camera_* symlinks need the same V4L2 setup as /dev/video0.
        local = isinstance(parsed, int) or os.path.realpath(str(parsed)).startswith("/dev/video")
        capture = (self.cv2.VideoCapture(parsed, self.cv2.CAP_V4L2)
                   if local and sys.platform.startswith("linux") else self.cv2.VideoCapture(parsed))
        if not capture.isOpened():
            capture.release()
            return None
        if local:
            if self.camera_fourcc:
                capture.set(self.cv2.CAP_PROP_FOURCC, self.cv2.VideoWriter_fourcc(*self.camera_fourcc[:4]))
            if self.camera_width > 0:
                capture.set(self.cv2.CAP_PROP_FRAME_WIDTH, self.camera_width)
            if self.camera_height > 0:
                capture.set(self.cv2.CAP_PROP_FRAME_HEIGHT, self.camera_height)
        if self.capture_fps > 0:
            capture.set(self.cv2.CAP_PROP_FPS, self.capture_fps)
        if hasattr(self.cv2, "CAP_PROP_BUFFERSIZE"):
            capture.set(self.cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def _ensure_worker(self):
        with self._condition:
            self._last_access = time.monotonic()
            if self.is_blocked_by_mode():
                return False
            if self._worker and self._worker.is_alive():
                return not self._stop.is_set()
            if self._last_access - self.last_open_attempt < 1.0:
                return False
            self.last_open_attempt = self._last_access
            self._stop = threading.Event()
            self._jpeg = None
            self._error = None
            self._worker = threading.Thread(target=self._produce, args=(self._stop,),
                                            name="latest-camera-frame", daemon=True)
            self._worker.start()
            return True

    def _produce(self, stop):
        capture = None
        try:
            capture = self._open_capture()
            if capture is None:
                raise RuntimeError("camera_open_failed")
            with self._condition:
                self.capture = capture
            next_encode = 0.0
            while not stop.is_set() and not self.is_blocked_by_mode():
                with self._condition:
                    if not self._clients and time.monotonic() - self._last_access > self.idle_timeout:
                        break
                # Always read at the device rate, even when HTTP output is slower.
                ok, frame = capture.read()
                captured_at = time.monotonic()
                if not ok:
                    raise RuntimeError("camera_read_failed")
                with self._condition:
                    self._frames_read += 1
                if captured_at < next_encode:
                    continue
                wall_time = time.time()
                if self.stream_width and frame.shape[1] > self.stream_width:
                    height = max(1, round(frame.shape[0] * self.stream_width / frame.shape[1]))
                    frame = self.cv2.resize(frame, (self.stream_width, height), interpolation=self.cv2.INTER_AREA)
                ok, encoded = self.cv2.imencode(".jpg", frame,
                                               [self.cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
                if not ok:
                    continue
                jpeg = encoded.tobytes()
                with self._condition:
                    if stop.is_set() or self.is_blocked_by_mode():
                        break
                    self._jpeg = jpeg
                    self._sequence += 1
                    self._captured_at = captured_at
                    self._wall_time = wall_time
                    self._frames_encoded += 1
                    self._condition.notify_all()
                next_encode = captured_at + 1.0 / self.target_fps
        except Exception as exc:
            with self._condition:
                self._error = str(exc)
                self._jpeg = None
        finally:
            # Only the reader thread releases its capture; never release during read().
            if capture is not None:
                capture.release()
            with self._condition:
                self.capture = None
                stop.set()
                self._condition.notify_all()

    def frame_snapshot(self, timeout=0.8, after_sequence=None, max_age=0.5):
        if not self._ensure_worker():
            return None
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while True:
                now = time.monotonic()
                if self.is_blocked_by_mode() or self._stop.is_set():
                    return None
                if (self._jpeg and now - self._captured_at <= max_age
                        and (after_sequence is None or self._sequence > after_sequence)):
                    return {"jpeg": self._jpeg, "sequence": self._sequence,
                            "age_ms": round((now - self._captured_at) * 1000, 2),
                            "captured_at": self._wall_time}
                remaining = deadline - now
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def open(self):
        return self.frame_snapshot() is not None

    def diagnostics(self):
        with self._condition:
            return {"frames_read": self._frames_read, "frames_encoded": self._frames_encoded,
                    "sequence": self._sequence, "jpeg_bytes": len(self._jpeg or b""),
                    "frame_age_ms": round((time.monotonic() - self._captured_at) * 1000, 2) if self._jpeg else None,
                    "running": bool(self._worker and self._worker.is_alive() and not self._stop.is_set()),
                    "target_fps": self.target_fps, "jpeg_quality": self.jpeg_quality,
                    "stream_width": self.stream_width, "error": self._error}

    def frames(self):
        with self._condition:
            self._clients += 1
        try:
            sequence = None
            while True:
                snapshot = self.frame_snapshot(after_sequence=sequence)
                if snapshot is None:
                    return
                sequence = snapshot["sequence"]
                jpeg = snapshot["jpeg"]
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode()
                       + b"\r\nX-Frame-Sequence: " + str(sequence).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
        finally:
            with self._condition:
                self._clients -= 1

    def close(self):
        with self._condition:
            self._stop.set()
            self._jpeg = None
            worker = self._worker
            self._condition.notify_all()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=0.5)
