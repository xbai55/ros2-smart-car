import assert from "node:assert/strict";
import test from "node:test";
import { calibrationPreview } from "../src/calibrationPreview";
import type { CalibrationPair, DrawingDescriptor } from "../src/labNavigation";
const drawing: DrawingDescriptor = { id:"test",name:"test",kind:"uploaded",width:1000,height:500 };
const points = [[0,0],[1000,0],[0,500],[1000,500]];
const pairs = (): CalibrationPair[] => points.map(([x,y])=>({drawing:{x,y},world:{x:3-y*.02,y:1+x*.01}}));
test("rotation, reflection and unequal scales do not imply registration error",()=>{
  const result=calibrationPreview(pairs(),drawing)!;
  assert.ok(result.maxError!<1e-10);assert.equal(result.concentrated,false);
});
test("inconsistent fourth corner produces visible residual in metres",()=>{
  const anchors=pairs();anchors[3].world.x+=.56;
  const result=calibrationPreview(anchors,drawing)!;
  assert.ok(Math.abs(result.maxError!-.14)<1e-9);
  assert.ok(result.errors!.every(e=>Math.abs(e-.14)<1e-9));
});
test("narrow anchor spread is warned about even with a perfect fit",()=>{
  const anchors=pairs().map(p=>({...p,drawing:{...p.drawing,y:p.drawing.y*.1}}));
  assert.equal(calibrationPreview(anchors,drawing)!.concentrated,true);
  const line=anchors.map(p=>({...p,drawing:{...p.drawing,y:100}}));
  assert.equal(calibrationPreview(line,drawing)!.maxError,null);
});
