"""Apply the bounded rotation gate fix to an isolated slam_toolbox 2.6.9 source tree."""
import argparse
from pathlib import Path

HEADER = r'''#pragma once
#include <cmath>
namespace slam_toolbox {
inline bool motionGateSatisfied(double distance_squared, double heading_delta,
                                double distance_threshold_squared, double heading_threshold) {
  const double angle = std::abs(std::atan2(std::sin(heading_delta), std::cos(heading_delta)));
  return distance_squared >= 0.8 * distance_threshold_squared || angle >= heading_threshold;
}
}
'''

TEST = r'''#include "slam_toolbox/motion_gate.hpp"
#include <cassert>
int main() {
  using slam_toolbox::motionGateSatisfied;
  const double threshold2 = 0.08 * 0.08;
  assert(!motionGateSatisfied(0, 0, threshold2, 0.08));
  assert(!motionGateSatisfied(0.02 * 0.02, 0.02, threshold2, 0.08));
  assert(motionGateSatisfied(0.09 * 0.09, 0, threshold2, 0.08));
  assert(motionGateSatisfied(0, 0.09, threshold2, 0.08));
  assert(motionGateSatisfied(0, -0.09, threshold2, 0.08));
  const double pi = std::acos(-1.0);
  assert(!motionGateSatisfied(0, 358 * pi / 180, threshold2, 0.08));
  assert(motionGateSatisfied(0, 350 * pi / 180, threshold2, 0.08));
}
'''


def apply(source: Path):
    package = source / "package.xml"
    if "<version>2.6.9</version>" not in package.read_text(encoding="utf-8"):
        raise RuntimeError("This patch is only audited for slam_toolbox 2.6.9")
    common = source / "src/slam_toolbox_common.cpp"
    text = common.read_text(encoding="utf-8")
    old = "if (dist2 < 0.8 * min_dist2 || scan_ctr < 5) {"
    new = """if (!motionGateSatisfied(dist2, pose.GetHeading() - last_pose.GetHeading(),
      min_dist2, smapper_->getMapper()->getParamMinimumTravelHeading()) || scan_ctr < 5) {"""
    include = '#include "slam_toolbox/slam_toolbox_common.hpp"'
    if "motionGateSatisfied" not in text:
        if text.count(old) != 1 or text.count(include) != 1:
            raise RuntimeError("Unexpected upstream source; refusing an ambiguous patch")
        text = text.replace(old, new).replace(include, include + '\n#include "slam_toolbox/motion_gate.hpp"')
        common.write_text(text, encoding="utf-8")
    (source / "include/slam_toolbox/motion_gate.hpp").write_text(HEADER, encoding="utf-8")
    (source / "motion_gate_test.cpp").write_text(TEST, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    apply(parser.parse_args().source)
    print("Isolated slam_toolbox 2.6.9 rotation patch applied")
