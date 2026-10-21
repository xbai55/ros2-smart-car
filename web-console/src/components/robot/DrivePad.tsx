import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, CircleStop, RotateCcw, RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRobotStream } from "../../hooks/useRobotStream";
import { bindDriveStops, canDrive, driveKeyCommand, DRIVE_KEYS, DRIVE_PROTECTED_TARGETS, DriveHoldController, LIVE_ROBOT_ID } from "../../liveControl";
import { cn } from "../../lib/cn";
const commands = [
  {id:"turn_l",label:"左旋",key:"Q",icon:RotateCcw}, {id:"forward",label:"前进",key:"W / ↑",icon:ArrowUp}, {id:"turn_r",label:"右旋",key:"E",icon:RotateCw},
  {id:"left",label:"左移",key:"A / ←",icon:ArrowLeft}, {id:"stop",label:"停止",key:"空格",icon:CircleStop}, {id:"right",label:"右移",key:"D / →",icon:ArrowRight},
  {id:"backward",label:"后退",key:"S / ↓",icon:ArrowDown},
];
export function DrivePad({ robotId = LIVE_ROBOT_ID }: {robotId?:string}) {
  const { status, connection, pending, sendCommand } = useRobotStream();
  const enabled = canDrive(status, connection === "connected", robotId) && !pending;
  const [active, setActive] = useState<string|null>(null);
  const controller = useRef<DriveHoldController|null>(null);
  const focusTarget = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const hold = new DriveHoldController(sendCommand, { every:(fn,ms)=>window.setInterval(fn,ms), clear:id=>clearInterval(id as number) }, setActive);
    controller.current = hold;
    return () => { hold.dispose(); controller.current = null; };
  }, [sendCommand, robotId]);
  useEffect(() => { controller.current?.stop(); }, [enabled, status.mode, status.emergency_stop, robotId]);
  useEffect(() => {
    const stop = () => controller.current?.stop();
    const unbind = bindDriveStops(window, document, stop);
    const keyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const command = driveKeyCommand(event, !!target?.closest(DRIVE_PROTECTED_TARGETS));
      if(command === "stop") { event.preventDefault(); controller.current?.stop(true); return; }
      if(enabled && command) { event.preventDefault(); if(!event.repeat) controller.current?.start(command); }
    };
    const keyUp = (event: KeyboardEvent) => { const key = event.key.length === 1 ? event.key.toLowerCase() : event.key; if(DRIVE_KEYS[key]) stop(); };
    const focusIn = (event: FocusEvent) => { if ((event.target as HTMLElement | null)?.closest(DRIVE_PROTECTED_TARGETS)) stop(); };
    window.addEventListener("keydown",keyDown); window.addEventListener("keyup",keyUp);
    document.addEventListener("focusin",focusIn);
    return () => { unbind(); window.removeEventListener("keydown",keyDown); window.removeEventListener("keyup",keyUp); document.removeEventListener("focusin",focusIn); };
  }, [enabled]);
  return <div className="live-drive" ref={focusTarget} tabIndex={-1} aria-label="键盘驾驶控制区">
    <div className="live-drive-heading"><strong>手动驾驶</strong><span>{active ? "正在行驶" : "按住行驶 · 松开停止"}</span></div>
    <button className="btn btn-outline" type="button" disabled={!enabled} onClick={() => focusTarget.current?.focus()}>点击此处使用键盘驾驶</button>
    <p className="live-helper">方向键 / WASD 驾驶，Q / E 转向，空格停止；Alt＋方向键平移地图。输入或调整滑条时暂停快捷键。</p>
    <div className="live-drive-pad">
      {commands.map(({id,label,key,icon:Icon})=><button key={id} type="button" className={cn("live-drive-button",id==="stop"&&"stop",id==="backward"&&"backward",active===id&&"pressed")}
        disabled={id==="stop" ? connection!=="connected" || robotId!==LIVE_ROBOT_ID : !enabled} aria-label={label}
        onPointerDown={e=>{if(e.button!==0)return;e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);controller.current?.start(id);}}
        onPointerUp={()=>controller.current?.stop()} onPointerCancel={()=>controller.current?.stop()} onLostPointerCapture={()=>controller.current?.stop()}
        onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();if(!e.repeat)controller.current?.start(id);}}}
        onKeyUp={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();controller.current?.stop();}}}>
        <Icon size={22}/><strong>{label}</strong><small>{key}</small>
      </button>)}
    </div>
    {!enabled && <p className="live-helper">{robotId!==LIVE_ROBOT_ID ? "未绑定实车，控制不可用" : status.emergency_stop ? "急停已锁定，请先解除急停并选择手动模式" : connection!=="connected" ? "连接小车后可使用手动驾驶" : pending ? "正在应用参数，请稍候" : status.mode==="mapping" && status.mapping.state==="error" ? "建图启动失败，请检查原因后重新建图" : status.mode==="mapping" && status.mapping.state!=="idle" ? "首张有效地图未就绪，请保持静止" : "选择手动驾驶或进入建图模式后可操控"}</p>}
  </div>;
}
