"""Portable keepout validation and conservative square footprint envelope."""
import math


def validate_keepout(snapshot):
    mask = snapshot.get('keepout')
    if mask is not None and (not isinstance(mask,list) or len(mask)!=len(snapshot['data']) or any(type(v) is not int or v not in (0,100) for v in mask)):
        raise ValueError('禁行遮罩尺寸或栅格无效')
    features = snapshot.get('map_features',[])
    if not isinstance(features,list) or any(f!='keepout-v1' for f in features):
        raise ValueError('地图需要车端不支持的功能')
    return mask


def inflate_keepout(mask,width,height,resolution,radius):
    """Square envelope is conservative for the configured circular footprint."""
    span=math.ceil(radius/resolution)
    if span>100: raise ValueError('该分辨率下禁行边界过大')
    horizontal, result = bytearray(width*height), bytearray(width*height)
    for y in range(height):
        base=y*width
        count=sum(bool(mask[base+x]) for x in range(min(width,span+1)))
        for x in range(width):
            horizontal[base+x]=bool(count)
            if x-span>=0: count-=bool(mask[base+x-span])
            if x+span+1<width: count+=bool(mask[base+x+span+1])
    for x in range(width):
        count=sum(horizontal[y*width+x] for y in range(min(height,span+1)))
        for y in range(height):
            result[y*width+x]=100 if count else 0
            if y-span>=0: count-=horizontal[(y-span)*width+x]
            if y+span+1<height: count+=horizontal[(y+span+1)*width+x]
    return list(result)
