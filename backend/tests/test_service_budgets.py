import pytest
from app.services import service_budgets as b


def test_wait_budgets_and_motion_expiry_are_separate():
    assert b.ACTION_WAIT==30 and b.NAVIGATION_START_WAIT==30
    assert b.CAPTURE_WAIT==15 and b.POSE_WAIT==120 and b.HANDOFF_TOTAL==300
    assert b.REVIEW_WAIT==45 and b.REVIEW_STALE==90


@pytest.mark.parametrize('value',['nan','inf','0','-1','601'])
def test_invalid_config_fails_instead_of_waiting_forever(monkeypatch,value):
    monkeypatch.setenv('INSIGHTROVER_TEST_WAIT',value)
    with pytest.raises(ValueError):b.budget('TEST_WAIT',1)
