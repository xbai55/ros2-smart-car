"""Measured rectangle in the existing base frame; no scan-axis correction."""
import math


class Rectangle:
    def __init__(self, front, rear, half_width):
        self.front,self.rear,self.half_width=map(float,(front,rear,half_width))
        self.left=self.right=self.half_width
        if not all(math.isfinite(v) and .01<=v<=1 for v in (self.front,self.rear,self.half_width)):
            raise ValueError('Invalid measured footprint')

    @property
    def radius(self):
        return math.hypot(max(self.front,self.rear),self.half_width)

    def translated_hull(self, dx, dy):
        hull=object.__new__(type(self))
        hull.front=self.front+max(0.,dx)
        hull.rear=self.rear+max(0.,-dx)
        hull.half_width=self.half_width+abs(dy)
        # The swept hull grows only towards the translation, never towards
        # the opposite side. Symmetric growth falsely approached rear corners.
        hull.left=self.left+max(0.,dy)
        hull.right=self.right+max(0.,-dy)
        return hull

    def local(self, point, pose):
        x,y=point[0]-pose[0],point[1]-pose[1]; c,s=math.cos(pose[2]),math.sin(pose[2])
        return c*x+s*y,-s*x+c*y

    def clearance(self, point, pose=(0,0,0)):
        x,y=self.local(point,pose)
        dx=max(-self.rear-x,0.,x-self.front)
        dy=max(-self.right-y,0.,y-self.left)
        if dx or dy:return math.hypot(dx,dy)
        return -min(x+self.rear,self.front-x,y+self.right,self.left-y)

    def ray_interval(self, origin, direction, pose=(0,0,0), margin=0.):
        ox,oy=self.local(origin,pose)
        c,s=math.cos(pose[2]),math.sin(pose[2]);rx=c*direction[0]+s*direction[1];ry=-s*direction[0]+c*direction[1]
        lo,hi=0.,float('inf')
        for o,d,left,right in ((ox,rx,-self.rear-margin,self.front+margin),
                                (oy,ry,-self.right-margin,self.left+margin)):
            if abs(d)<1e-10:
                if not left<=o<=right:return None
            else:
                a,b=sorted(((left-o)/d,(right-o)/d));lo=max(lo,a);hi=min(hi,b)
                if hi<lo:return None
        return lo,hi

    def check(self, evidence, pose, margin, direction=None, reference=None):
        """Return blocking evidence; rotation gets no separation exception.

        Unknown rays are tested against a conservative rectangular expansion,
        which contains the rounded safety offset used for known obstacles.
        """
        ref=reference or self
        bound_squared=(self.radius+margin)**2
        for p in evidence.points:
            if (p[0]-pose[0])**2+(p[1]-pose[1])**2>bound_squared:continue
            distance=self.clearance(p,pose)
            if distance>margin:continue
            if direction is not None:
                # Contact at the boundary may separate or remain parallel;
                # an actual return inside the body must still stop motion.
                if distance>=-1e-8 and ref.clearance(p)>=-1e-8 and distance+1e-8>=ref.clearance(p):
                    continue
            return {'kind':'obstacle','point':list(p),'clearance_m':distance}
        if getattr(evidence, 'distance_only', False):return None
        if not evidence.full:return {'kind':'unknown','reason':'cropped_scan'}
        extra=(math.hypot(*pose[:2])+self.radius+margin+math.hypot(*evidence.origin))*abs(math.sin(evidence.step))
        visible_bound=math.dist(pose[:2],evidence.origin)+self.radius+(margin+extra)*math.sqrt(2)+.01
        if all(v is not None and v>visible_bound for v in evidence.visibility_ranges):return None
        for value,ray in zip(evidence.visibility_ranges,evidence.ray_directions):
            interval=self.ray_interval(evidence.origin,ray,pose,margin+extra)
            if interval is None:continue
            lo,hi=interval
            lo=max(lo,value-.01 if value is not None else 0.)
            body=ref.ray_interval(evidence.origin,ray)
            if body and body[0]<=lo<=body[1]:lo=max(lo,body[1])
            if lo>=hi:continue
            if direction is not None:
                dx,dy=direction
                ends=[(evidence.origin[0]+t*ray[0],evidence.origin[1]+t*ray[1]) for t in (lo,hi)]
                # A straight translation never sweeps physical body into a ray
                # segment wholly outside its parallel side. Do not require a
                # previously unobserved stationary side halo to become observed.
                # Turning/diagonal motion deliberately receives no exemption.
                if abs(dy)<1e-10 and abs(dx)>0:
                    if all(y>=ref.half_width-1e-9 for _,y in ends) or all(y<=-ref.half_width+1e-9 for _,y in ends):
                        continue
                if abs(dx)<1e-10 and abs(dy)>0:
                    if all(x>=ref.front-1e-9 for x,_ in ends) or all(x<=-ref.rear+1e-9 for x,_ in ends):
                        continue
                # Unknown space entirely behind the moving rectangle is not
                # certified free, but is not approached by straight motion.
                def approach(t):
                    px,py=evidence.origin[0]+t*ray[0],evidence.origin[1]+t*ray[1]
                    values=[]
                    if dx:values.append(dx*(px-(ref.front if dx>0 else -ref.rear)))
                    if dy:values.append(dy*(py-(ref.half_width if dy>0 else -ref.half_width)))
                    return max(values,default=0.)
                if max(approach(t) for t in (lo,hi)) < -extra*math.hypot(dx,dy):
                    continue
            t=lo+(hi-lo)/2
            return {'kind':'unknown','point':[evidence.origin[0]+t*ray[0],evidence.origin[1]+t*ray[1]]}
        return None
