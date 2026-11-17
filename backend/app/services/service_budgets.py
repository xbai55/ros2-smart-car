"""Service waiting budgets; never used for motion evidence expiry."""
import math
import os

def budget(name, default):
    value=float(os.getenv('INSIGHTROVER_'+name,str(default)))
    if not math.isfinite(value) or not 0 < value <= 600:
        raise ValueError('Invalid service wait budget: '+name)
    return value

ACTION_WAIT=budget('ACTION_WAIT_SEC',30)
NAVIGATION_START_WAIT=budget('NAVIGATION_START_WAIT_SEC',30)
CAPTURE_WAIT=budget('CAPTURE_WAIT_SEC',15)
POSE_WAIT=budget('POSE_WAIT_SEC',120)
HANDOFF_TOTAL=budget('HANDOFF_TOTAL_SEC',300)
REVIEW_WAIT=budget('REVIEW_WAIT_SEC',45)
REVIEW_STALE=budget('REVIEW_STALE_SEC',90)
if REVIEW_STALE <= REVIEW_WAIT:raise ValueError('Review expiry must exceed response wait')
