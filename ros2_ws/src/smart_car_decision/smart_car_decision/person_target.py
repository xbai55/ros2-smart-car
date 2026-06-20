class PersonTargetSelector:
    """Keep one detected person locked across frames using center continuity."""

    def __init__(self, lost_timeout_sec=0.8, max_center_jump_ratio=0.3):
        self.lost_timeout_sec = max(0.0, float(lost_timeout_sec))
        self.max_center_jump_ratio = max(0.0, float(max_center_jump_ratio))
        self.locked_box = None
        self.last_seen_time = 0.0

    def update(self, candidates, frame_width, now):
        people = [item for item in candidates if item.get("class_name") == "person"]
        now = float(now)
        frame_width = max(1.0, float(frame_width))

        if self.locked_box is None:
            return self._acquire(people, frame_width, now)

        matched = self._nearest_locked_person(people, frame_width)
        if matched is not None:
            self.locked_box = tuple(matched["xyxy"])
            self.last_seen_time = now
            return matched

        if now - self.last_seen_time <= self.lost_timeout_sec:
            return None

        self.locked_box = None
        return self._acquire(people, frame_width, now)

    def reset(self):
        self.locked_box = None
        self.last_seen_time = 0.0

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
        self.locked_box = tuple(selected["xyxy"])
        self.last_seen_time = now
        return selected

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
