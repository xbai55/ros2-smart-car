from smart_car_decision.person_target import PersonTargetSelector


def candidate(class_name, confidence, x1, x2, track_id=None):
    return {
        "class_name": class_name,
        "confidence": confidence,
        "xyxy": (x1, 40.0, x2, 220.0),
        "track_id": track_id,
    }


def test_selector_ignores_every_class_except_person():
    selector = PersonTargetSelector()

    selected = selector.update(
        [candidate("car", 0.99, 250, 390), candidate("dog", 0.95, 100, 220)],
        frame_width=640,
        now=1.0,
    )

    assert selected is None


def test_selector_initially_picks_high_confidence_person():
    selector = PersonTargetSelector()
    left = candidate("person", 0.91, 80, 200)
    right = candidate("person", 0.72, 430, 570)

    assert selector.update([right, left], frame_width=640, now=1.0) == left


def test_selector_keeps_same_person_when_detection_order_and_confidence_change():
    selector = PersonTargetSelector(max_center_jump_ratio=0.3)
    person_a = candidate("person", 0.90, 70, 190)
    person_b = candidate("person", 0.80, 430, 570)
    selector.update([person_a, person_b], frame_width=640, now=1.0)

    person_a_next = candidate("person", 0.62, 85, 205)
    person_b_next = candidate("person", 0.99, 420, 560)

    assert selector.update([person_b_next, person_a_next], frame_width=640, now=1.1) == person_a_next


def test_selector_waits_for_loss_timeout_before_switching_people():
    selector = PersonTargetSelector(lost_timeout_sec=0.8, max_center_jump_ratio=0.2)
    person_a = candidate("person", 0.90, 70, 190)
    person_b = candidate("person", 0.95, 440, 570)
    selector.update([person_a], frame_width=640, now=1.0)

    assert selector.update([person_b], frame_width=640, now=1.4) is None
    assert selector.update([person_b], frame_width=640, now=1.9) == person_b


def test_selector_keeps_bytetrack_id_when_people_cross():
    selector = PersonTargetSelector()
    selected = candidate("person", 0.90, 70, 190, track_id=7)
    other = candidate("person", 0.80, 430, 570, track_id=9)
    selector.update([selected, other], frame_width=640, frame_height=480, now=1.0)

    selected_crossed = candidate("person", 0.70, 390, 520, track_id=7)
    other_crossed = candidate("person", 0.99, 100, 230, track_id=9)

    assert selector.update(
        [other_crossed, selected_crossed], frame_width=640, frame_height=480, now=1.1
    ) == selected_crossed


def test_manual_point_selects_containing_track_and_never_switches_after_timeout():
    selector = PersonTargetSelector(lost_timeout_sec=0.8)
    left = candidate("person", 0.95, 40, 180, track_id=2)
    right = candidate("person", 0.75, 400, 600, track_id=5)
    selector.select_point(0.8, 0.25)

    assert selector.update(
        [left, right], frame_width=640, frame_height=480, now=1.0
    ) == right
    assert selector.update([left], frame_width=640, frame_height=480, now=2.0) is None
    assert selector.status(now=2.0)["state"] == "waiting"
    assert selector.update([left], frame_width=640, frame_height=480, now=3.0) is None


def test_returning_to_auto_reacquires_best_person():
    selector = PersonTargetSelector(lost_timeout_sec=0.8)
    person = candidate("person", 0.88, 220, 400, track_id=11)
    selector.select_point(0.1, 0.1)
    assert selector.update([person], frame_width=640, frame_height=480, now=1.0) is None

    selector.select_auto()

    assert selector.update(
        [person], frame_width=640, frame_height=480, now=1.1
    ) == person
    assert selector.status(now=1.1)["selection_mode"] == "auto"
