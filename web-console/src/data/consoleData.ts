import {
  ArrowDown, ArrowLeft, ArrowRight, ArrowUp, CircleStop, Crosshair, Gamepad2,
  Hexagon, Map, Navigation, Radio, Route, ShieldCheck, Target
} from "lucide-react";

export type ModeId = "stop" | "manual" | "auto" | "mapping" | "navigation" | "color_track" | "object_follow";

export const modes = [
  { id: "stop" as ModeId, name: "停止", command: "stop", description: "车辆保持静止，适合调试和待机", icon: CircleStop },
  { id: "manual" as ModeId, name: "手动", command: "manual", description: "网页方向键通过后端发布手动指令", icon: Gamepad2 },
  { id: "auto" as ModeId, name: "自动避障", command: "auto", description: "融合雷达安全避障进行自动行驶", icon: Route },
  { id: "mapping" as ModeId, name: "建图", command: "mapping", description: "切换到 SLAM 建图工作流", icon: Map },
  { id: "navigation" as ModeId, name: "导航", command: "navigation", description: "保留 Nav2 底盘控制权", icon: Navigation },
  { id: "color_track" as ModeId, name: "颜色追踪", command: "color_track", description: "HSV 目标追踪并输出偏移量", icon: Crosshair },
  { id: "object_follow" as ModeId, name: "目标跟随", command: "object_follow", description: "YOLO 目标跟随并输出控制", icon: Target }
];

export const modeFocusText: Record<ModeId, string> = {
  stop: "底盘输出保持为零，适合调试、换场地或等待传感器稳定。",
  manual: "手动模式接收网页遥控指令，适合架空测试底盘响应和方向映射。",
  auto: "自动避障结合雷达前方距离生成安全速度，遇到近障碍优先停车。",
  mapping: "建图模式让 SLAM 链路接管环境感知，控制台显示实时状态。",
  navigation: "导航模式保留 Nav2 控制权，避免网页端抢占 /cmd_vel。",
  color_track: "颜色追踪读取 HSV 目标偏移量，形成视觉闭环。",
  object_follow: "目标跟随根据 YOLO 结果输出偏移，形成感知控制闭环。"
};

export const modeDetails: Record<ModeId, { headline: string; actions: string[] }> = {
  stop: { headline: "底盘锁定，所有速度指令被置零。", actions: ["确认保持状态", "检查节点在线", "需要遥控时切到手动"] },
  manual: { headline: "网页方向键发布手动控制指令。", actions: ["测试前进后退", "检查左右方向", "停止键优先"] },
  auto: { headline: "雷达前方距离参与避障决策。", actions: ["查看实时雷达", "确认前方无遮挡", "观察自动速度"] },
  mapping: { headline: "SLAM 建图链路接管环境感知。", actions: ["启动 SLAM", "保存地图", "检查 TF 树"] },
  navigation: { headline: "Nav2 负责全局路径与局部规划。", actions: ["检查定位", "发送目标点", "观察路径状态"] },
  color_track: { headline: "HSV 阈值锁定颜色目标。", actions: ["应用 HSV 配置", "观察目标偏移", "切换颜色预设"] },
  object_follow: { headline: "YOLO 结果转为跟随控制。", actions: ["检查 YOLO 节点", "观察目标框", "确认低速跟随"] }
};

export const colorPresets = [
  { name: "red", label: "红色", dot: "#ff5f68", lower: [0, 80, 80], upper: [12, 255, 255] },
  { name: "green", label: "绿色", dot: "#43e889", lower: [35, 70, 70], upper: [85, 255, 255] },
  { name: "blue", label: "蓝色", dot: "#22b7ff", lower: [95, 80, 80], upper: [130, 255, 255] },
  { name: "yellow", label: "黄色", dot: "#ffd45a", lower: [18, 70, 90], upper: [34, 255, 255] }
];

export const baseStatusCards = [
  { key: "mode", title: "当前模式", value: "", description: "", icon: ShieldCheck },
  { key: "interlock", title: "安全互锁", value: "", description: "", icon: ShieldCheck },
  { key: "distance", title: "前方距离", value: "", description: "来自 /scan", icon: Navigation },
  { key: "offset", title: "偏移量", value: "", description: "来自视觉话题", icon: Crosshair }
];

export const quickResults = [
  { key: "command", title: "最近命令", value: "", description: "", icon: Radio },
  { key: "yolo", title: "YOLO 结果", value: "", description: "", icon: Hexagon },
  { key: "color", title: "颜色目标", value: "", description: "", icon: Crosshair }
];

export const manualCommands = [
  { id: "forward", label: "前进", icon: ArrowUp, slot: "top" },
  { id: "turn_l", label: "左旋", icon: ArrowLeft, slot: "middle-left" },
  { id: "stop", label: "停止", icon: CircleStop, slot: "middle-center", danger: true },
  { id: "turn_r", label: "右旋", icon: ArrowRight, slot: "middle-right" },
  { id: "left", label: "左移", icon: ArrowLeft, slot: "bottom-left" },
  { id: "backward", label: "后退", icon: ArrowDown, slot: "bottom-center" },
  { id: "right", label: "右移", icon: ArrowRight, slot: "bottom-right" }
];
