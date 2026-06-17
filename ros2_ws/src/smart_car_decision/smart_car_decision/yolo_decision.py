SAFETY_COMMANDS = {"stop", "red_light", "shutdown"}
MOTION_COMMANDS = {
    "green_light",
    "no_light",
    "slow",
    "limiting_velocity",
    "school_decelerate",
}


def normalize_candidate_command(command, default_command="no_light"):
    command = str(command or "").strip().lower().replace("-", "_").replace(" ", "_")
    if command in SAFETY_COMMANDS or command in MOTION_COMMANDS:
        return command
    return default_command


def is_frame_obscured(frame, min_brightness=20.0, min_contrast=6.0):
    if frame is None:
        return True
    return float(frame.mean()) < min_brightness or float(frame.std()) < min_contrast


class YoloCommandFilter:
    def __init__(self, default_command="no_light", safety_hold_sec=0.8):
        self.default_command = default_command
        self.safety_hold_sec = float(safety_hold_sec)
        self._safety_command = None
        self._safety_until = 0.0

    def update(self, command, now):
        command = normalize_candidate_command(command, self.default_command)
        if command in SAFETY_COMMANDS:
            self._safety_command = command
            self._safety_until = float(now) + self.safety_hold_sec
            return command
        if self._safety_command is not None and float(now) <= self._safety_until:
            return self._safety_command
        self._safety_command = None
        return command
