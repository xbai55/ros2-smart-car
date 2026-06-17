import sys
from pathlib import Path


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "ros2_ws"
    / "src"
    / "smart_car_decision"
)
sys.path.insert(0, str(PACKAGE_ROOT))
