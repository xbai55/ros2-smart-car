import { Palette, SlidersHorizontal, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";
import { colorPresets } from "../data/consoleData";
import type { ColorConfig, ColorTarget } from "../robotApi";
import { colorConfigKey } from "../colorPersistence";
import { HudPanel } from "./HudPanel";

type Props = { config: ColorConfig; target: ColorTarget | null; onApply: (config: ColorConfig) => void };
const labels = ["H min", "S min", "V min", "H max", "S max", "V max"];

export function ColorConfigPanel({ config, target, onApply }: Props) {
  const [draft, setDraft] = useState(config);
  const configKey = colorConfigKey(config);
  useEffect(() => setDraft(config), [configKey]);

  const values = [...draft.hsv_low, ...draft.hsv_high];
  const updateValue = (index: number, value: number) => {
    const next = [...values];
    next[index] = Math.max(0, Math.min(index % 3 === 0 ? 179 : 255, value));
    setDraft({ ...draft, name: "custom", hsv_low: next.slice(0, 3) as ColorConfig["hsv_low"], hsv_high: next.slice(3) as ColorConfig["hsv_high"] });
  };

  return (
    <HudPanel className="color-config-panel" title="Color Track" subtitle="颜色追踪配置" action={<span className="tag-pill">/vision/color_config</span>}>
      <div className="color-config-body">
        <div className="preset-row">{colorPresets.map((preset)=>(
          <button key={preset.name} type="button" className={`preset-chip ${draft.name === preset.name ? "active" : ""}`} onClick={()=>setDraft({
            name: preset.name,
            hsv_low: [...preset.lower] as ColorConfig["hsv_low"],
            hsv_high: [...preset.upper] as ColorConfig["hsv_high"]
          })}><i style={{background:preset.dot}}/><span>{preset.label}</span></button>
        ))}</div>
        <div className="hsv-grid">{labels.map((label,index)=>(
          <label key={label}><span>{label}</span><input type="number" value={values[index]} min="0" max={index % 3 === 0 ? 179 : 255} onChange={(event)=>updateValue(index,Number(event.currentTarget.value))}/></label>
        ))}</div>
        <div className="color-status-strip">
          <span><Palette size={15}/>当前：{draft.name} {draft.hsv_low.join(",")} / {draft.hsv_high.join(",")}</span>
          <span><SlidersHorizontal size={15}/>偏移量 {target?.offset == null ? "--" : target.offset.toFixed(4)}</span>
          <button type="button" onClick={()=>onApply(draft)}><UploadCloud size={15}/>应用配置</button>
        </div>
      </div>
    </HudPanel>
  );
}
