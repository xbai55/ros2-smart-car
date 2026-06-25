class PersonTargetSelector:
    """Lock one person by ByteTrack ID, with a legacy center-distance fallback."""

    def __init__(self, lost_timeout_sec=0.8, max_center_jump_ratio=0.3):
        self.lost_timeout_sec = max(0.0, float(lost_timeout_sec))
        self.max_center_jump_ratio = max(0.0, float(max_center_jump_ratio))
        self.selection_mode = "auto"
        self.locked_track_id = None
        self.locked_box = None
        self.pending_point = None
        self.last_seen_time = 0.0

    def update(self, candidates, frame_width, now, frame_height=1):
        people = [item for item in candidates if item.get("class_name") == "person"]
        now = float(now)
        frame_width = max(1.0, float(frame_width))
        frame_height = max(1.0, float(frame_height))

        if self.selection_mode == "manual" and self.pending_point is not None:
            selected = self._select_at_point(people, frame_width, frame_height)
            if selected is None:
                return None
            self.pending_point = None
            return self._lock(selected, now)

        if self.locked_track_id is not None:
            matched = next(
                (item for item in people if item.get("track_id") == self.locked_track_id),
                None,
            )
        elif self.locked_box is not None:
            matched = self._nearest_locked_person(people, frame_width)
        else:
            matched = None

        if matched is not None:
            return self._lock(matched, now)

        if self.locked_box is not None and now - self.last_seen_time <= self.lost_timeout_sec:
            return None

        self.locked_track_id = None
        self.locked_box = None
        if self.selection_mode == "manual":
            return None
        return self._acquire(people, frame_width, now)

    def select_point(self, x, y):
        x = float(x)
        y = float(y)
        if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            raise ValueError("target coordinates must be normalized to [0, 1]")
        self.selection_mode = "manual"
        self.pending_point = (x, y)
        self.locked_track_id = None
        self.locked_box = None
        self.last_seen_time = 0.0

    def select_auto(self):
        self.selection_mode = "auto"
        self.pending_point = None
        self.locked_track_id = None
        self.locked_box = None
        self.last_seen_time = 0.0

    def reset(self):
        self.select_auto()

    def status(self, now):
        if self.locked_box is not None:
            state = "locked"
        elif self.selection_mode == "manual":
            state = "selecting" if self.pending_point is not None else "waiting"
        else:
            state = "searching"
        return {
            "selection_mode": self.selection_mode,
            "state": state,
            "locked": state == "locked",
            "track_id": self.locked_track_id,
            "last_seen_age": None
            if self.last_seen_time <= 0.0
            else round(max(0.0, float(now) - self.last_seen_time), 3),
        }

    def _acquire(self, people, frame_width, now):
        if not people:
            return None
        frame_center = frame_width / 2.0
        selected = max(
            people,
            key=lambda item: (
                float(item.get("confidence", 0.0)),
                -abs(self._center_x(item["xyxy"]) - frame_center),
            ),
        )
        return self._lock(selected, now)

    def _lock(self, selected, now):
        self.locked_track_id = selected.get("track_id")
        self.locked_box = tuple(selected["xyxy"])
        self.last_seen_time = float(now)
        return selected

    def _select_at_point(self, people, frame_width, frame_height):
        px = self.pending_point[0] * frame_width
        py = self.pending_point[1] * frame_height
        containing = [
            item
            for item in people
            if item.get("track_id") is not None
            and float(item["xyxy"][0]) <= px <= float(item["xyxy"][2])
            and float(item["xyxy"][1]) <= py <= float(item["xyxy"][3])
        ]
        if not containing:
            return None
        return max(containing, key=lambda item: float(item.get("confidence", 0.0)))

    def _nearest_locked_person(self, people, frame_width):
        if not people:
            return None
        locked_center = self._center_x(self.locked_box)
        selected = min(people, key=lambda item: abs(self._center_x(item["xyxy"]) - locked_center))
        jump_ratio = abs(self._center_x(selected["xyxy"]) - locked_center) / frame_width
        return selected if jump_ratio <= self.max_center_jump_ratio else None

    @staticmethod
    def _center_x(xyxy):
        return (float(xyxy[0]) + float(xyxy[2])) / 2.0
