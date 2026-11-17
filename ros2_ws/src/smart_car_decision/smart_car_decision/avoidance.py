"""Map-free, bounded obstacle detours. Geometry and state are independent of ROS."""
import math
import time
from .avoidance_settings import DEFAULTS

BUILD_ID = "avoidance-4.0.8-distance-basic"

ZERO = {"linear_x": 0.0, "linear_y": 0.0, "angular_z": 0.0}
MIN_CLEARANCE_M = .05


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class ScanEvidence:
    """Finite laser returns define observed free rays; absent returns are unknown."""
    def __init__(self, scan, transform=(0.0, 0.0, 0.0), self_returns=(), footprint=None, gap_width_m=0., ray_kinds=None,
                 assume_missing_clear=False):
        self.origin = transform[:2]
        self.step = abs(float(scan.angle_increment))
        self.rays = []
        self.points = []
        self.buckets = {}
        self.disk_cache = {}
        self.sequence = (scan.header.stamp.sec, scan.header.stamp.nanosec)
        self.full = self.step * len(scan.ranges) >= 2 * math.pi - 2 * self.step
        self.start = float(scan.angle_min) + transform[2]
        self.increment = float(scan.angle_increment)
        self.self_return_count = 0
        masked=set()
        inference_eligible=set()
        self.ray_directions = [(math.cos(self.start+i*self.increment), math.sin(self.start+i*self.increment))
                               for i in range(len(scan.ranges))]
        for i, value in enumerate(scan.ranges):
            value = float(value)
            if value==math.inf and (ray_kinds is None or ray_kinds[i] in {'unknown','unsampled'}):inference_eligible.add(i)
            valid = math.isfinite(value) and scan.range_min <= value <= scan.range_max
            self.rays.append(value if valid else None)
            if valid:
                angle = self.start + i * self.increment
                point=(transform[0] + value * math.cos(angle),transform[1] + value * math.sin(angle))
                if footprint is not None and footprint.clearance(point)<-1e-8:
                    # Operator policy: strictly interior returns belong to the
                    # measured body. Boundary/exterior points remain obstacles.
                    # Their shadows still use the separate visibility policy.
                    self.rays[-1]=None
                    masked.add(i)
                    self.self_return_count+=1
                else:self.points.append(point)
        for point in self.points:
            self.buckets.setdefault((math.floor(point[0] / .25), math.floor(point[1] / .25)), []).append(point)
        self._visibility=None
        self.inferred_ray_count=0
        self.sampling_gap_inferred=None
        self.duplicate_direction_observations=0
        base=list(self.rays)
        if self.full and len(base)>2 and abs(wrap((len(base)-1)*self.increment))<1e-5:
            measured=[v for v in (base[0],base[-1]) if v is not None]
            if measured:
                for index in (0,len(base)-1):
                    if base[index] is None and index not in masked and (ray_kinds is None or ray_kinds[index] not in {'invalid','body_occluded'}):
                        base[index]=min(measured);self.duplicate_direction_observations+=1
                if self.duplicate_direction_observations:self._visibility=base
        if gap_width_m>0 and self.full and self.step>0:
            visible=list(base); n=len(visible); inferred=[]
            for i,v in enumerate(base):
                if v is not None or i in masked or i not in inference_eligible:continue
                left=right=None
                for d in range(1,7):
                    j=(i-d)%n
                    if j in masked:break
                    if base[j] is not None:left=(d,base[j]);break
                    if j not in inference_eligible:break
                for d in range(1,7):
                    j=(i+d)%n
                    if j in masked:break
                    if base[j] is not None:right=(d,base[j]);break
                    if j not in inference_eligible:break
                if left and right:
                    angle=(left[0]+right[0])*self.step
                    cap=gap_width_m/angle
                    # Compare depths only within the region we certify. A wall
                    # edge metres beyond the cap cannot invalidate near-field
                    # bounded evidence; a near edge still rejects inference.
                    a,b=min(left[1],cap),min(right[1],cap)
                    consistent=abs(a-b)<=max(.10,min(a,b)*.1)
                    if left[0]+right[0]<=6 and angle<=math.radians(2.1) and consistent:
                        visible[i]=min(left[1],right[1],gap_width_m/angle)
                        self.inferred_ray_count+=1
                        inferred.append(visible[i])
            self._visibility=visible
            if inferred:self.sampling_gap_inferred={'kind':'sampling_gap_inferred','rays':len(inferred),
                'distance_cap_min_m':min(inferred),'distance_cap_max_m':max(inferred),'gap_width_limit_m':gap_width_m,
                'consistency_region':'within_inferred_distance'}
        self.assumed_clear={'kind':'operator_assumed_clear','rays':0,'body_shadow_rays':0,'device_proven':False,
                            'body_filter_policy':'measured_rectangle_interior','body_filtered_rays':self.self_return_count}
        if assume_missing_clear and self.full and ray_kinds is not None:
            visible=list(self.visibility_ranges)
            body_hits={index for index in masked if ray_kinds[index]=='hit'}
            for index in inference_eligible | body_hits:
                # This existing operator policy also waives body-return shadows.
                # External real points remain in the obstacle/visibility checks.
                visible[index]=float(scan.range_max)
                self.assumed_clear['rays']+=1
                if index in masked:self.assumed_clear['body_shadow_rays']+=1
            self._visibility=visible
            self.assumed_clear['distance_cap_m']=float(scan.range_max)

    @property
    def visibility_ranges(self):
        return self.rays if self._visibility is None else self._visibility

    def reframe(self, x, y, yaw):
        """Move a stamped scan into the current body frame without changing rays."""
        result = object.__new__(ScanEvidence)
        result.__dict__ = self.__dict__.copy()
        c, s = math.cos(yaw), math.sin(yaw)
        def transform(point):
            return x+c*point[0]-s*point[1], y+s*point[0]+c*point[1]
        result.origin = transform(self.origin)
        result.start = self.start+yaw
        result.ray_directions = [(c*dx-s*dy, s*dx+c*dy) for dx,dy in self.ray_directions]
        result.points = [transform(point) for point in self.points]
        result.buckets, result.disk_cache = {}, {}
        for point in result.points:
            result.buckets.setdefault((math.floor(point[0]/.25), math.floor(point[1]/.25)), []).append(point)
        return result

    def observed(self, x, y):
        dx, dy = x - self.origin[0], y - self.origin[1]
        distance = math.hypot(dx, dy)
        if distance < .015:
            return True
        if not self.rays or self.step <= 0:
            return False
        angle = math.atan2(dy, dx)
        offset = (angle - self.start) % (2 * math.pi) if self.increment > 0 else (self.start - angle) % (2 * math.pi)
        index = offset / self.step
        lo = math.floor(index)
        indices = (lo, lo + 1)
        if not self.full and (lo < 0 or lo + 1 >= len(self.rays)):
            return False
        values = [self.visibility_ranges[i % len(self.rays)] for i in indices]
        return all(v is not None and v >= distance + .01 for v in values)

    def free_disk(self, x, y, radius):
        key = (round(x, 5), round(y, 5), round(radius, 5))
        if key in self.disk_cache:
            return self.disk_cache[key]
        nearby = (p for ix in range(math.floor((x-radius)/.25), math.floor((x+radius)/.25)+1)
                  for iy in range(math.floor((y-radius)/.25), math.floor((y+radius)/.25)+1)
                  for p in self.buckets.get((ix, iy), ()))
        if any(math.hypot(px - x, py - y) <= radius for px, py in nearby):
            self.disk_cache[key] = False
            return False
        # Sampling spacing is bounded by 3 cm, also for larger footprints.
        count = max(48, math.ceil(2 * math.pi * radius / .03))
        result = self.observed(x, y) and all(self.observed(x + radius * math.cos(i * 2 * math.pi / count),
                                                        y + radius * math.sin(i * 2 * math.pi / count)) for i in range(count))
        self.disk_cache[key] = result
        return result

    def free_segment(self, start, end, radius):
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        count = max(1, math.ceil(length / .025))
        return all(self.free_disk(start[0] + (end[0] - start[0]) * i / count,
                                  start[1] + (end[1] - start[1]) * i / count, radius) for i in range(count + 1))

    def collision_free(self, x, y, radius):
        return not any(math.hypot(px-x, py-y) <= radius for px, py in self.points)

    def directional_collision_free(self, x, y, radius, direction):
        """A commanded straight translation may separate from a rear obstacle.

        No point is removed: an obstacle inside the conservative envelope is
        tolerated only while both behind the instantaneous translation and
        no closer than initially. Rotation never uses this exception.
        """
        for px, py in self.points:
            distance = math.hypot(px-x, py-y)
            if distance > radius:
                continue
            if ((px-x)*direction[0]+(py-y)*direction[1] >= -1e-8
                    or distance+1e-8 < math.hypot(px, py)):
                return False
        return True

    def translation_free(self, x, y, radius, physical_radius):
        """Require evidence wherever a translated disk approaches unknown space.

        Unknown space behind a straight translation is not certified free. It
        may only be omitted when its distance to the footprint cannot decrease.
        Real returns are never omitted, including inside the initial envelope.
        Rotation uses the stricter full-disk check in the controller.
        """
        length = math.hypot(x, y)
        if length < 1e-8:
            return self.collision_free(x, y, radius)
        ux, uy = x/length, y/length
        if not self.directional_collision_free(x, y, radius, (ux, uy)):
            return False
        if not self.full or not self.rays or self.step <= 0:
            # Cropped scans retain the explicit spatial coverage check.
            return self.free_disk(x, y, radius)
        ox, oy = self.origin
        dx, dy = x-ox, y-oy
        # Expand by one ray spacing so an unknown angular wedge cannot slip
        # between center rays. Finite returns start an occluded shadow too.
        spacing = (math.hypot(dx,dy)+radius)*abs(math.sin(self.step))
        expanded = radius+spacing
        center_squared = dx*dx+dy*dy
        for value,(rx,ry) in zip(self.visibility_ranges,self.ray_directions):
            projection = dx*rx+dy*ry
            disc = expanded*expanded-center_squared+projection*projection
            if disc < 0:
                continue
            root = math.sqrt(disc)
            lo = max(0.,projection-root, value-.01 if value is not None else 0.)
            hi = projection+root
            if hi < lo:
                continue
            body = max(0.,physical_radius-spacing)
            if math.hypot(ox+lo*rx,oy+lo*ry) <= body:
                origin_projection = ox*rx+oy*ry
                body_disc = body*body-ox*ox-oy*oy+origin_projection*origin_projection
                if body_disc >= 0:
                    lo = max(lo,-origin_projection+math.sqrt(body_disc))
                    if lo >= hi:
                        continue
            endpoints = ((ox+lo*rx,oy+lo*ry),(ox+hi*rx,oy+hi*ry))
            # Distance along a ray is convex: endpoints bound the entire
            # interval, so only the actual body interior can be excluded.
            if max(math.hypot(px,py) for px,py in endpoints) <= max(0.,physical_radius-spacing):
                continue
            if max(px*ux+py*uy for px,py in endpoints) >= -spacing:
                return False
        return True

    def translation_segment_free(self, start, end, radius, physical_radius):
        count = max(1, math.ceil(math.dist(start, end)/.025))
        return all(self.translation_free(start[0]+(end[0]-start[0])*i/count,
                                         start[1]+(end[1]-start[1])*i/count,
                                         radius, physical_radius) for i in range(1,count+1))

    def front_clearance(self, radius):
        values = [x - math.sqrt(max(0.0, radius * radius - y * y))
                  for x, y in self.points if x >= 0 and abs(y) <= radius]
        return max(0.0, min(values)) if values else None


class DistanceOnlyEvidence:
    """Known returns only; never changes raw rays or declares unknown rays clear."""
    distance_only = True

    def __init__(self, source):
        self.source = source

    def __getattr__(self, name):
        return getattr(self.source, name)

    def free_disk(self, x, y, radius):
        return self.source.collision_free(x, y, radius)

    def translation_free(self, x, y, radius, physical_radius):
        return self.source.directional_collision_free(x, y, radius, (x, y))


class AvoidanceController:
    def __init__(self, radius=.25, timeout=45.0, max_speed=.25, speed_ratio=.8, motion_model='differential'):
        if motion_model not in {'differential','holonomic'}:
            raise ValueError('Unsupported avoidance motion model')
        self.motion_model=motion_model
        self.radius = float(radius)
        if not math.isfinite(self.radius) or not .01 <= self.radius <= 2.0:
            raise ValueError('Invalid avoidance footprint radius')
        self.timeout = timeout
        self.max_speed, self.speed_ratio = max_speed, speed_ratio
        self.settings = dict(DEFAULTS)
        self.last_stop_event = None
        self.requested_motion = dict(ZERO)
        self.applied_motion = dict(ZERO)
        self.reason_code = "idle"
        self.footprint = None
        self.reset()
        self.state = "waiting"
        self.reason = "等待控制器设置确认"

    def reset(self):
        self.last_arc = dict(ZERO)
        self.last_arc_at = 0.
        self.state, self.reason, self.direction = "idle", "待命", None
        self.path = []
        self.anchor = None
        self.distance = 0.0
        self.previous_pose = None
        self.clear_since = None
        self.last_mode = None
        self.last_sequence = None
        self.confirmations = 0
        self.front = None
        self.blocking_point = None
        self.coverage = {'kind': 'not_evaluated'}

    def status(self):
        return {"state": self.state, "reason": self.reason, "direction": self.direction,
                "build_id": BUILD_ID,
                "motion_model": self.motion_model,
                "missing_data_policy": getattr(self,'missing_data_policy',{'mode':'observed_only'}),
                "assumed_clear": getattr(self,'assumed_clear',None),
                "minimum_clearance_m": MIN_CLEARANCE_M,
                "reason_code": self.reason_code,
                "requested_motion": self.requested_motion,
                "applied_motion": self.applied_motion,
                "blocking_point_m": self.blocking_point,
                "coverage": self.coverage,
                "scan_provenance": getattr(self,'scan_provenance',{'source':'legacy_scan'}),
                "scan_health": getattr(self,'scan_health',{}),
                "sampling_gap_inferred": getattr(self,'sampling_gap_inferred',None),
                "recovery_condition": '原运动意图仍有效且新扫描证明通道可用' if self.state=='waiting_observation' else None,
                "front_clearance_m": self.front, "distance_m": round(self.distance, 3),
                "last_stop_event": self.last_stop_event}

    def stop(self, state, reason):
        self.state, self.reason = state, reason
        if state in {"blocked", "sensor_fault", "timeout", "braking", "waiting_observation"}:
            self.last_stop_event = {"state": state, "reason": reason, "mode": self.last_mode,
                                    "timestamp": time.time(),
                                    "blocking_point_m": self.blocking_point,
                                    "coverage": dict(self.coverage),
                                    "front_clearance_m": self.front}
        return dict(ZERO)

    @staticmethod
    def local(p, pose):
        dx, dy = p[0] - pose[0], p[1] - pose[1]
        c, s = math.cos(pose[2]), math.sin(pose[2])
        return c * dx + s * dy, -s * dx + c * dy

    @staticmethod
    def world(p, pose):
        c, s = math.cos(pose[2]), math.sin(pose[2])
        return pose[0] + c * p[0] - s * p[1], pose[1] + s * p[0] + c * p[1]

    def guard(self, motion, evidence, radius):
        if getattr(self, "distance_only_guard", False) and not getattr(evidence, "distance_only", False):
            evidence = DistanceOnlyEvidence(evidence)
        vx, vy, w = (motion[k] for k in ZERO)
        if not any((vx, vy, w)):
            return dict(ZERO)
        # Reduce speed before rejecting a safe but narrow path. Actual speed also
        # contributes, so a smaller command cannot pretend the car stopped instantly.
        for factor in (1.0, .75, .5, .25):
            cx, cy, cw = vx * factor, vy * factor, w * factor
            speed = max(self.actual_speed, math.hypot(cx, cy))
            envelope = radius + speed * self.scan_age + speed ** 2 / .6
            duration = max(1., .6 + speed / .3)
            x = y = yaw = 0.0
            rotating = abs(cw) > 1e-6
            if self.footprint is not None:
                failure=None
                if not rotating:
                    # The axis-aligned hull contains every intermediate
                    # translated footprint, so one check covers the full path.
                    f=self.footprint; dx,dy=cx*duration,cy*duration
                    swept=f.translated_hull(dx,dy)
                    failure=swept.check(evidence,(0,0,0),envelope-self.radius,(cx,cy),reference=f)
                    if failure is None:
                        self.coverage={'kind':'clear','motion':'translation','shape':'measured_rectangle'}
                        self.blocking_point=None
                        return dict(zip(ZERO,(cx,cy,cw)))
                    self.blocking_point=failure.get('point')
                    self.coverage={**failure,'motion':'translation','shape':'measured_rectangle'}
                    continue
                samples=max(1,math.ceil(max(math.hypot(cx,cy)*duration/.025,abs(cw)*duration/.025)))
                dt=duration/samples
                for _ in range(samples):
                    x+=(math.cos(yaw)*cx-math.sin(yaw)*cy)*dt
                    y+=(math.sin(yaw)*cx+math.cos(yaw)*cy)*dt
                    yaw+=cw*dt
                    failure=self.footprint.check(evidence,(x,y,yaw),envelope-self.radius,
                                                  None if rotating else (cx,cy))
                    if failure:break
                if failure is None:
                    self.coverage={'kind':'clear','motion':'turn' if rotating else 'translation','shape':'measured_rectangle'}
                    self.blocking_point=None
                    return dict(zip(ZERO,(cx,cy,cw)))
                self.blocking_point=failure.get('point')
                self.coverage={**failure,'motion':'turn' if rotating else 'translation','shape':'measured_rectangle'}
                continue
            safe = (evidence.free_disk(0, 0, envelope) if rotating else
                    evidence.directional_collision_free(0, 0, envelope, (cx, cy)))
            for _ in range(max(1, math.ceil(duration / .05))):
                x += (math.cos(yaw) * cx - math.sin(yaw) * cy) * .05
                y += (math.sin(yaw) * cx + math.cos(yaw) * cy) * .05
                yaw += cw * .05
                clear = (evidence.free_disk(x, y, envelope) if rotating else
                         evidence.translation_free(x, y, envelope, self.radius))
                if not safe or not clear:
                    safe = False
                    break
            if safe:
                self.coverage = {'kind': 'clear', 'motion': 'turn' if rotating else 'translation'}
                self.blocking_point = None
                return dict(zip(ZERO, (cx, cy, cw)))
        if self.footprint is None:
            near = [p for p in evidence.points if math.hypot(*p) <= envelope]
            self.blocking_point = list(min(near,key=lambda p: math.hypot(*p))) if near else None
            self.coverage = {'kind': 'obstacle' if near else 'unknown_or_swept_collision',
                             'motion': 'turn' if rotating else 'translation'}
        reason = '转向扫过区域存在近障或缺少观测' if rotating else '平移轨迹净空不足或缺少观测'
        unknown=self.coverage.get('kind') in {'unknown','unknown_or_swept_collision'}
        return self.stop('waiting_observation' if unknown else ('braking' if self.actual_speed>.01 else 'blocked'), reason)

    def choose(self, evidence, pose, radius):
        if self.motion_model=='holonomic':
            return self.choose_translation(evidence,pose,radius)
        self._choice_unobserved=False
        width = self.footprint.half_width + radius-self.radius if self.footprint else radius
        obstacles = [(x, y) for x, y in evidence.points if x > 0 and abs(y) <= width]
        if not obstacles:
            return False
        obstacle_x = min(x for x, _ in obstacles)
        candidates = []
        for sign in (1, -1):
            for offset in (.50, .55, .60, .65, .8):
                offset = max(offset, radius + .15)
                first = (max(.08, obstacle_x - .20), sign * offset)
                last = (obstacle_x + radius + .08, sign * offset)
                length = math.hypot(*first) + last[0] - first[0]
                if length > 1.5:
                    continue
                # Approve only a short observable prefix; occluded far waypoints
                # are intentions and are rechecked by guard on every cycle.
                prefix_length = min(.20, math.hypot(*first))
                prefix = tuple(v*prefix_length/math.hypot(*first) for v in first)
                failure=self.footprint.check(evidence,(*prefix,0),radius-self.radius,first) if self.footprint else None
                prefix_safe=(failure is None if self.footprint else evidence.translation_segment_free((0,0),prefix,radius,self.radius))
                if failure and failure.get('kind')=='unknown':self._choice_unobserved=True
                if prefix_safe:
                    # Prefer actual obstacle clearance, then shorter paths; left wins ties.
                    clearance = min(math.hypot(px - first[0], py - first[1]) for px, py in evidence.points)
                    # Known obstacles on the intended continuation still count;
                    # only its unknown visibility is deferred.
                    count = max(1, math.ceil(length/.05))
                    known_safe=lambda x,y,direction: (all(self.footprint.clearance(p,(x,y,0))>radius-self.radius
                                                        or (p[0]<0 and self.footprint.clearance(p,(x,y,0))>=self.footprint.clearance(p))
                                                        for p in evidence.points) if self.footprint else evidence.directional_collision_free(x,y,radius,direction))
                    if not all(known_safe(first[0]*i/count, first[1]*i/count, first)
                               for i in range(count+1)):
                        continue
                    if not all(known_safe(first[0]+(last[0]-first[0])*i/count, first[1], (1,0))
                               for i in range(count+1)):
                        continue
                    score = round(min(clearance, 1.0) - .20 * length, 6)
                    candidates.append((score, sign, first, last))
        if not candidates:
            return False
        _, sign, first, last = max(candidates, key=lambda item: (item[0], item[1]))
        self.anchor = pose
        self.path = [self.world(first, pose), self.world(last, pose)]
        self.direction = "left" if sign > 0 else "right"
        self.state, self.reason = "turning", "向左绕行" if sign > 0 else "向右绕行"
        return True

    def choose_translation(self, evidence, pose, radius):
        """Mecanum detour: lateral departure then forward, with fixed heading."""
        self._choice_unobserved=False
        f=self.footprint
        if f is None:return False
        margin=radius-self.radius
        front=[x for x,y in evidence.points if x>=f.front and abs(y)<=f.half_width+margin]
        if not front:return False
        obstacle_x=min(front)
        candidates=[]
        for sign in (1,-1):
            # Include short offsets: a narrow valid lane can lie between the
            # front obstacle and a side wall that rejects every >=25 cm detour.
            for offset in (.15,.20,.25,.30,.35,.40,.45,.50,.55,.60,.65):
                first=(0.,sign*offset)
                last=(obstacle_x+f.front+margin+.10,sign*offset)
                if offset+last[0]>1.5:continue
                prefix=(0.,sign*min(.15,offset))
                failure=f.translated_hull(*prefix).check(evidence,(0,0,0),margin,
                                                          (0.,sign),reference=f)
                if failure:
                    if failure['kind']=='unknown':self._choice_unobserved=True
                    continue
                # Reject real collisions on both entire translation legs.
                # Only visibility beyond the immediate prefix is deferred.
                safe=True
                for start,delta in (((0.,0.),first),(first,(last[0],0.))):
                    hull=f.translated_hull(*delta)
                    for p in evidence.points:
                        clearance=hull.clearance(p,(*start,0.))
                        initial=f.clearance(p,(*start,0.))
                        if clearance<=margin and not (clearance>=-1e-8 and initial>=-1e-8 and clearance+1e-8>=initial):
                            safe=False;break
                    if not safe:break
                if not safe:continue
                clearance=min((f.clearance(p,(*first,0.)) for p in evidence.points),default=1.)
                score=round(min(clearance,1.)-.2*(offset+last[0]),6)
                candidates.append((score,sign,first,last))
        if not candidates:return False
        _,sign,first,last=max(candidates,key=lambda item:(item[0],item[1]))
        self.anchor=pose
        self.path=[self.world(first,pose),self.world(last,pose)]
        self.direction='left' if sign>0 else 'right'
        self.state,self.reason='passing','保持朝向，向左横移绕行' if sign>0 else '保持朝向，向右横移绕行'
        return True

    def step(self, motion, **kwargs):
        self.requested_motion = dict(motion)
        result = self._step(motion, **kwargs)
        self.applied_motion = dict(result)
        self.reason_code = self.state
        return result

    def _step(self, motion, *, mode, now, evidence, scan_age, pose, odom_age,
             confirmed=True, legacy_stop=0.0, actual_speed=0.0):
        if mode != self.last_mode:
            self.reset()
            self.last_mode = mode
        if not all(math.isfinite(float(v)) for v in motion.values()):
            return self.stop("sensor_fault", "运动指令无效")
        if not any(motion.values()) or mode == "stop":
            self.reset()
            self.last_mode = mode
            return dict(ZERO)
        if self.path and motion['linear_x'] <= 0:
            self.reset()
            self.last_mode = mode
        if not confirmed:
            return self.stop("waiting", "等待控制器设置确认")
        if evidence is None or scan_age > .6 or pose is None or odom_age > .5:
            return self.stop("sensor_fault", "雷达、坐标变换或里程计不可用")
        if self.previous_pose is not None:
            delta = math.hypot(pose[0] - self.previous_pose[0], pose[1] - self.previous_pose[1])
            if delta > .20 or abs(wrap(pose[2] - self.previous_pose[2])) > .5:
                return self.stop("sensor_fault", "里程计发生跳变，请停止后重新发起运动")
            self.distance += delta
        self.previous_pose = pose
        # Operator-selected base buffer; braking and legacy limits can enlarge it.
        margin = max(MIN_CLEARANCE_M, float(legacy_stop) - self.radius)
        radius = self.radius + margin
        self.actual_speed, self.scan_age = actual_speed, scan_age
        corridor_clearance = evidence.front_clearance(radius)
        trigger_clearance = None if corridor_clearance is None else corridor_clearance + margin
        self.front = evidence.front_clearance(self.radius)
        if self.footprint:
            f=self.footprint
            values=[x-f.front for x,y in evidence.points if x>=f.front and abs(y)<=f.half_width+margin]
            trigger_clearance=max(0.,min(values)) if values else None
            self.front=trigger_clearance
        if self.state in {"sensor_fault", "blocked", "timeout"}:
            return dict(ZERO)
        straight = not self.path and abs(motion['angular_z']) < 1e-6
        initial_clear = (evidence.directional_collision_free(0, 0, radius,
                          (motion['linear_x'], motion['linear_y'])) if straight else
                         evidence.collision_free(0, 0, radius))
        if self.footprint:
            # The swept rectangle check distinguishes approaching, parallel and
            # separating clearance; a circular initial gate would undo that.
            initial_clear=True
        if not initial_clear and not self.path:
            near = [p for p in evidence.points if math.hypot(*p) <= radius
                    and (not straight or p[0]*motion['linear_x']+p[1]*motion['linear_y'] >= -1e-8)]
            self.blocking_point = list(min(near,key=lambda p:math.hypot(*p))) if near else None
            self.coverage = {'kind': 'obstacle', 'motion': 'translation' if straight else 'turn'}
            return self.stop("blocked", "车体周围存在低于安全余量的障碍")
        if mode == "navigation" or not self.settings["enabled"] or (not self.path and motion["linear_x"] <= 0):
            self.state, self.reason = ("nav2", "由 Nav2 规划绕行") if mode == "navigation" else ("idle", "仅防撞停车" if not self.settings["enabled"] else "待命")
            return self.guard(motion, evidence, radius)
        if self.anchor is not None:
            if now - self.started_at > self.timeout or self.distance > 1.5:
                return self.stop("timeout", "绕行超时或超过距离上限，请停止后重试")
        if self.path:
            if self.motion_model=='holonomic' and abs(wrap(pose[2]-self.anchor[2]))>.12:
                return self.stop('sensor_fault','横移绕行期间朝向偏差过大，请停止后重试')
            target = self.path[0]
            dx, dy = self.local(target, pose)
            if math.hypot(dx, dy) < .04:
                self.path.pop(0)
                self.state = "recovering"
            if self.path:
                dx, dy = self.local(self.path[0], pose)
                if self.motion_model=='holonomic':
                    # Do not rotate or reverse to chase a waypoint. Re-evaluate
                    # the complete translation sweep on every controller tick.
                    dx=max(0.,dx)
                    distance=math.hypot(dx,dy)
                    speed=min(self.max_speed,self.speed_ratio*max(0.,motion['linear_x']),distance)
                    self.state='passing'
                    self.reason='保持朝向，横移避让' if len(self.path)==2 else '保持朝向，向前通过'
                    return self.guard({**ZERO,'linear_x':speed*dx/max(distance,1e-9),
                                       'linear_y':speed*dy/max(distance,1e-9)},evidence,radius)
                error = math.atan2(dy, dx)
                speed = min(self.max_speed, self.speed_ratio * max(0.0, motion["linear_x"]))
                result = dict(ZERO)
                result["angular_z"] = max(-.25, min(.25, 2.0 * error))
                if abs(error) < .6:
                    distance=math.hypot(dx,dy)
                    # Bound curvature so the arc can reach a nearby waypoint
                    # instead of orbiting it at a minimum turning radius.
                    curvature_speed=.25*distance/max(.1,2*abs(math.sin(error)))
                    result["linear_x"] = min(speed * max(0., math.cos(error)), distance, curvature_speed)
                    self.state = "passing"
                else:
                    self.state = "turning" if len(self.path) == 2 else "recovering"
                return self.follow_candidates(result, evidence, radius, dx, dy, now)
        if self.anchor is not None:
            error = wrap(self.anchor[2] - pose[2])
            self.state, self.reason = "recovering", "恢复原行驶方向"
            if self.motion_model=='holonomic' and abs(error)>.12:
                return self.stop('sensor_fault','横移绕行期间朝向偏差过大，请停止后重试')
            if self.motion_model!='holonomic' and abs(error) > .05:
                return self.guard({**ZERO, "angular_z": max(-.25, min(.25, 2.0 * error))}, evidence, radius)
            release = max(.75, self.settings["trigger_distance_m"] + .15)
            release_safe=(self.footprint.check(evidence,(min(release,.2),0,0),margin,(1,0)) is None
                          if self.footprint else evidence.translation_segment_free((0, 0), (release, 0), radius, self.radius))
            if (self.front is not None and self.front < release) or not release_safe:
                self.clear_since = None
                return dict(ZERO)
            self.clear_since = now if self.clear_since is None else self.clear_since
            if now - self.clear_since < .5:
                return dict(ZERO)
            self.reset()
            self.last_mode = mode
        if trigger_clearance is not None and trigger_clearance <= self.settings["trigger_distance_m"]:
            self.state, self.reason = "assessing", "制动并判断绕行方向"
            if evidence.sequence != self.last_sequence:
                self.confirmations += 1
                self.last_sequence = evidence.sequence
            if self.confirmations >= 2:
                if not self.choose(evidence, pose, radius):
                    return self.stop('waiting_observation' if self._choice_unobserved else 'blocked', "左右均无足够的已观测通行空间")
                self.started_at = now
                self.distance = 0.0
            return dict(ZERO)
        self.confirmations = 0
        self.state, self.reason = "idle", "待命"
        return self.guard(motion, evidence, radius)

    def follow_candidates(self, motion, evidence, radius, dx, dy, now):
        """Short-horizon differential-drive candidates; execute only swept-safe arcs."""
        old=(self.state,self.reason)
        previous_stop=self.last_stop_event
        previous=getattr(self,'last_arc',ZERO)
        dt=min(.1,max(.01,now-getattr(self,'last_arc_at',now-.05)))
        target_w=max(previous['angular_z']-.5*dt,min(previous['angular_z']+.5*dt,motion['angular_z']))
        candidates=[]
        # Keep path steering sign; a locked detour never switches sides here.
        for factor in (1.,.7,.4):
            for w in (target_w,target_w*.75):
                v=motion['linear_x']*factor
                trial={**ZERO,'linear_x':v,'angular_z':w}
                self.state,self.reason=old
                safe=self.guard(trial,evidence,radius)
                if not any(safe.values()):continue
                v,w=safe['linear_x'],safe['angular_z']
                x,y=(v*math.sin(w)/w,v*(1-math.cos(w))/w) if abs(w)>1e-6 else (v,0.)
                heading=math.atan2(dy,dx)
                score=(math.hypot(dx,dy)-math.hypot(dx-x,dy-y)
                       +.2*(abs(heading)-abs(wrap(heading-w)))-.05*abs(w-previous['angular_z']))
                candidates.append((score,safe,self.blocking_point,self.coverage))
        if not candidates:
            self.state,self.reason=old
            return self.guard({**motion,'angular_z':target_w},evidence,radius)
        _,result,point,coverage=max(candidates,key=lambda v:v[0])
        self.state,self.reason=old
        self.last_stop_event=previous_stop
        self.blocking_point,self.coverage=point,coverage
        self.last_arc,self.last_arc_at=dict(result),now
        return result
