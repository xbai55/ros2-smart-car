const modes = [
  ["stop", "停止", "车辆保持静止，适合调试和待机", "S"],
  ["manual", "手动", "允许网页方向键发布 /manual_cmd", "M"],
  ["auto", "自动避障", "融合雷达安全策略进行自动行驶", "A"],
  ["mapping", "建图", "交给厂商 SLAM 链路，不直接发布速度", "P"],
  ["navigation", "导航", "交给 Nav2 链路，不抢占 /cmd_vel", "N"],
  ["color_track", "颜色追踪", "HSV 目标追踪并输出偏移量", "C"],
  ["object_follow", "目标跟随", "YOLO 目标偏移转为跟随控制", "O"],
];

const colorPresets = {
  green: { label: "绿色", swatch: "#22c55e", hsv_low: [35, 60, 60], hsv_high: [90, 255, 255] },
  red: { label: "红色", swatch: "#ef4444", hsv_low: [0, 80, 80], hsv_high: [12, 255, 255] },
  blue: { label: "蓝色", swatch: "#3b82f6", hsv_low: [95, 80, 60], hsv_high: [130, 255, 255] },
  yellow: { label: "黄色", swatch: "#facc15", hsv_low: [20, 80, 80], hsv_high: [34, 255, 255] },
};

const modeContexts = {
  stop: {
    title: "停止待机",
    text: "底盘输出保持为零，适合调试、换场地或等待传感器稳定。",
    steps: ["确认急停状态", "检查节点在线", "需要遥控时切到手动"],
  },
  manual: {
    title: "手动遥控",
    text: "网页方向键会连续发送 /manual_cmd，松手自动停车。",
    steps: ["解除急停", "调低速度比例", "按住方向键测试"],
  },
  auto: {
    title: "自动避障",
    text: "决策节点融合雷达距离和视觉结果输出 /cmd_vel。",
    steps: ["确认雷达正常", "确认场地安全", "观察前方距离"],
  },
  mapping: {
    title: "建图准备",
    text: "交给厂商 SLAM 链路，本控制台只保留状态观察和急停。",
    steps: ["启动 SLAM 相关节点", "保持低速移动", "观察地图链路"],
  },
  navigation: {
    title: "导航任务",
    text: "交给 Nav2 链路，不抢占 /cmd_vel，只保留安全态势观察。",
    steps: ["确认定位已稳定", "加载地图", "观察导航状态"],
  },
  color_track: {
    title: "颜色追踪",
    text: "颜色追踪节点使用 HSV 范围寻找目标，并把偏移量发布到 /lane/offset。",
    steps: ["选择目标颜色", "必要时微调 HSV", "观察颜色目标和偏移量"],
  },
  object_follow: {
    title: "目标跟随",
    text: "YOLO 目标偏移会转成跟随控制，适合演示视觉目标追踪。",
    steps: ["确认 YOLO 画面", "保持目标在视野内", "观察 YOLO 结果"],
  },
};

const modeMap = new Map(modes.map(([value, label, description]) => [value, { label, description }]));
const modeButtons = document.querySelector("#modeButtons");
const modeFeedback = document.querySelector("#modeFeedback");
const colorFeedback = document.querySelector("#colorFeedback");
const videoFeed = document.querySelector("#videoFeed");
const videoOverlay = document.querySelector("#videoOverlay");
const remotePanel = document.querySelector(".remote");
const alertBanner = document.querySelector("#alertBanner");
const speedScale = document.querySelector("#speedScale");
const speedDefaultHint = document.querySelector("#speedDefaultHint");
const DEFAULT_SPEED_KEY = "smart-car-default-speed";
const DEFAULT_COLOR_KEY = "smart-car-color-config";
const MIN_SPEED_SCALE = 0.15;

const state = {
  emergency: false,
  pollingTimer: null,
  websocket: null,
  controlSocket: null,
  controlSocketReady: false,
  lastMode: "stop",
  activeCommand: "",
  commandTimer: null,
  colorConfig: { name: "green", ...colorPresets.green },
  colorConfigDirty: false,
};

for (const [value, label, description, shortLabel] of modes) {
  const button = document.createElement("button");
  button.innerHTML = `<span class="mode-icon">${shortLabel}</span><span><strong>${label}</strong><small>${description}</small></span>`;
  button.title = description;
  button.dataset.mode = value;
  button.type = "button";
  button.addEventListener("click", () => setMode(value, label));
  modeButtons.appendChild(button);
}

for (const [name, preset] of Object.entries(colorPresets)) {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.color = name;
  button.innerHTML = `<i style="--swatch:${preset.swatch}"></i><span>${preset.label}</span>`;
  button.addEventListener("click", () => {
    state.colorConfigDirty = true;
    setColorInputs({ name, ...preset });
    renderColorPresetSelection(name);
    applyColorConfig();
  });
  document.querySelector("#colorPresets").appendChild(button);
}

document.querySelectorAll("[data-command]").forEach((button) => {
  const command = button.dataset.command;
  const begin = (event) => {
    event.preventDefault();
    button.setPointerCapture?.(event.pointerId);
    if (command === "stop") {
      stopManualCommand();
      return;
    }
    startManualCommand(command);
  };
  button.addEventListener("pointerdown", begin);
  button.addEventListener("mousedown", begin);
  button.addEventListener("touchstart", begin, { passive: false });
  if (command !== "stop") {
    window.addEventListener("pointerup", stopManualCommand);
    window.addEventListener("pointercancel", stopManualCommand);
    window.addEventListener("mouseup", stopManualCommand);
    window.addEventListener("touchend", stopManualCommand);
    window.addEventListener("touchcancel", stopManualCommand);
    button.addEventListener("contextmenu", (event) => event.preventDefault());
  }
});

document.querySelector("#emergencyBtn").addEventListener("click", async () => {
  const next = !state.emergency;
  try {
    await postJson("/api/emergency-stop", { enabled: next });
    state.emergency = next;
    setFeedback(next ? "已急停，底盘输出被锁定。" : "已解除急停，请重新确认模式和速度。", "ok");
    await refreshStatus();
  } catch (error) {
    setFeedback(error.message, "error");
  }
});

speedScale.addEventListener("input", async (event) => {
  const scale = normalizeSpeedScale(event.target.value);
  event.target.value = scale;
  document.querySelector("#speedValue").textContent = `${Math.round(scale * 100)}%`;
  try {
    await postJson("/api/speed", { scale });
  } catch (error) {
    setFeedback(error.message, "error");
  }
});

document.querySelector("#saveSpeedBtn").addEventListener("click", () => {
  const scale = normalizeSpeedScale(speedScale.value);
  speedScale.value = scale;
  localStorage.setItem(DEFAULT_SPEED_KEY, String(scale));
  renderDefaultSpeedHint(scale, true);
});

document.querySelector("#applyColorBtn").addEventListener("click", applyColorConfig);
document.querySelector("#reloadVideoBtn").addEventListener("click", reloadVideo);
document.querySelector("#autoTargetBtn").addEventListener("click", async () => {
  try {
    await postJson("/api/tracking-target", { action: "auto" });
    setFeedback("已切换为自动选择人物。", "ok");
  } catch (error) {
    setFeedback(error.message, "error");
  }
});
document.querySelectorAll("#colorPanel input").forEach((input) => {
  input.addEventListener("input", () => {
    state.colorConfigDirty = true;
    document.querySelector("#colorConfigName").textContent = "custom";
    renderColorPresetSelection("");
  });
});
videoFeed.addEventListener("load", () => setVideoMessage("", true));
videoFeed.addEventListener("click", async (event) => {
  if (state.lastMode !== "object_follow") {
    return;
  }
  const point = imageClickPoint(event, videoFeed);
  try {
    await postJson("/api/tracking-target", { action: "select", ...point });
    setFeedback("已发送目标点，请等待 ByteTrack 锁定人物。", "ok");
  } catch (error) {
    setFeedback(error.message, "error");
  }
});
videoFeed.addEventListener("error", () => {
  videoFeed.classList.add("is-broken");
  setVideoMessage("摄像头不可用或正在被识别节点占用", false);
});

async function setMode(mode, label) {
  setFeedback(`正在切换到 ${label}...`);
  try {
    await postJson("/api/mode", { mode });
    state.lastMode = mode;
    setFeedback(`已切换到 ${label}。`, "ok");
    await refreshStatus();
    reloadVideo();
  } catch (error) {
    setFeedback(error.message, "error");
  }
}

async function applyColorConfig() {
  const payload = readColorInputs();
  state.colorConfigDirty = true;
  try {
    const result = await postJson("/api/color-target", payload);
    const config = result.color_config || payload;
    state.colorConfig = config;
    state.colorConfigDirty = false;
    localStorage.setItem(DEFAULT_COLOR_KEY, JSON.stringify(config));
    renderColorConfig(config);
    colorFeedback.textContent = `已应用 ${formatColorName(config.name)}，颜色追踪节点会使用新的 HSV 范围。`;
    colorFeedback.classList.add("is-ok");
    colorFeedback.classList.remove("is-error");
  } catch (error) {
    state.colorConfigDirty = false;
    colorFeedback.textContent = error.message;
    colorFeedback.classList.add("is-error");
    colorFeedback.classList.remove("is-ok");
  }
}

async function sendCommand(command) {
  const manualReady = state.lastMode === "manual" && !state.emergency;
  if (!manualReady && command !== "stop") {
    setFeedback("手动遥控被锁定：请先解除急停并切换到 manual 模式。", "error");
    return;
  }
  try {
    sendControlCommand(command);
    document.querySelector("#lastCommand").textContent = command;
  } catch (error) {
    if (command !== "stop") {
      setFeedback(error.message, "error");
    }
  }
}

function sendControlCommand(command) {
  if (state.controlSocketReady && state.controlSocket?.readyState === WebSocket.OPEN) {
    state.controlSocket.send(JSON.stringify({ command }));
    return;
  }
  postJson("/api/command", { command }, true).catch((error) => {
    if (command !== "stop") {
      setFeedback(error.message, "error");
    }
  });
}

function startManualCommand(command) {
  if (state.activeCommand === command && state.commandTimer) {
    return;
  }
  stopCommandTimer();
  state.activeCommand = command;
  sendCommand(command);
  state.commandTimer = window.setInterval(() => {
    sendCommand(command);
  }, 60);
}

function stopManualCommand() {
  const hadActiveCommand = Boolean(state.activeCommand || state.commandTimer);
  stopCommandTimer();
  state.activeCommand = "";
  if (hadActiveCommand) {
    sendCommand("stop");
  }
}

function connectControl() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws/control`);
  state.controlSocket = ws;
  ws.onopen = () => {
    state.controlSocketReady = true;
  };
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.command) {
        document.querySelector("#lastCommand").textContent = data.command;
      }
    } catch {
      // Ignore malformed control acknowledgements.
    }
  };
  ws.onerror = () => {
    ws.close();
  };
  ws.onclose = () => {
    state.controlSocketReady = false;
    if (state.controlSocket === ws) {
      setTimeout(connectControl, 1000);
    }
  };
}

async function applyDefaultSpeed() {
  const saved = Number(localStorage.getItem(DEFAULT_SPEED_KEY));
  const scale = Number.isFinite(saved) ? normalizeSpeedScale(saved) : 1;
  speedScale.value = scale;
  document.querySelector("#speedValue").textContent = `${Math.round(scale * 100)}%`;
  renderDefaultSpeedHint(scale, false);
  try {
    await postJson("/api/speed", { scale });
  } catch (error) {
    setFeedback(error.message, "error");
  }
}

async function applySavedColor() {
  let config = { name: "green", ...colorPresets.green };
  try {
    config = JSON.parse(localStorage.getItem(DEFAULT_COLOR_KEY)) || config;
  } catch {
    config = { name: "green", ...colorPresets.green };
  }
  state.colorConfigDirty = true;
  setColorInputs(config);
  renderColorConfig(config);
  try {
    const result = await postJson("/api/color-target", config);
    const applied = result.color_config || config;
    state.colorConfig = applied;
    localStorage.setItem(DEFAULT_COLOR_KEY, JSON.stringify(applied));
    renderColorConfig(applied);
  } catch (error) {
    colorFeedback.textContent = `保存的颜色配置下发失败：${error.message}`;
    colorFeedback.classList.add("is-error");
  } finally {
    state.colorConfigDirty = false;
  }
}

function renderDefaultSpeedHint(scale, savedNow) {
  const percent = Math.round(scale * 100);
  speedDefaultHint.textContent = savedNow
    ? `已保存默认速度：${percent}%`
    : `当前默认速度：${percent}%`;
}

function stopCommandTimer() {
  if (state.commandTimer) {
    window.clearInterval(state.commandTimer);
    state.commandTimer = null;
  }
}

async function postJson(url, body, ignoreConflict = false) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok && !(ignoreConflict && response.status === 409)) {
    let detail = "";
    try {
      const data = await response.json();
      detail = data.detail ? `：${data.detail}` : "";
    } catch {
      detail = "";
    }
    throw new Error(`请求失败 ${response.status}${detail}`);
  }
  return response.json().catch(() => ({}));
}

function connectStatus() {
  stopPolling();
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws/status`);
  state.websocket = ws;

  ws.onopen = () => {
    document.querySelector("#connectionState").textContent = "已连接";
    document.querySelector("#statusChannel").textContent = "WebSocket";
  };
  ws.onmessage = (event) => {
    renderStatus(JSON.parse(event.data));
  };
  ws.onerror = () => {
    ws.close();
  };
  ws.onclose = () => {
    if (state.websocket === ws) {
      document.querySelector("#connectionState").textContent = "HTTP 轮询";
      document.querySelector("#statusChannel").textContent = "HTTP";
      startPolling();
      setTimeout(connectStatus, 5000);
    }
  };
}

function startPolling() {
  if (state.pollingTimer) {
    return;
  }
  refreshStatus();
  state.pollingTimer = setInterval(refreshStatus, 1000);
}

function stopPolling() {
  if (state.pollingTimer) {
    clearInterval(state.pollingTimer);
    state.pollingTimer = null;
  }
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    renderStatus(await response.json());
  } catch (error) {
    document.querySelector("#connectionState").textContent = "状态断开";
    document.querySelector("#statusChannel").textContent = "离线";
    showAlert("连接中断", "无法获取 /api/status，请检查 ROS2 web_app_node 是否仍在运行。", "danger");
  }
}

function renderStatus(status) {
  state.emergency = Boolean(status.emergency_stop);
  const mode = status.mode ?? "stop";
  state.lastMode = mode;

  document.querySelector("#modeValue").textContent = modeMap.get(mode)?.label ?? mode;
  document.querySelector("#modeDescription").textContent = modeMap.get(mode)?.description ?? "未知模式";
  document.querySelector("#estopValue").textContent = `急停 ${String(state.emergency)}`;
  document.querySelector("#frontDistance").textContent = formatDistance(status.front_distance);
  document.querySelector("#detectionValue").textContent = status.detection || "--";
  document.querySelector("#laneOffset").textContent =
    status.lane_offset == null ? "--" : Number(status.lane_offset).toFixed(3);
  document.querySelector("#lastCommand").textContent = status.last_command || "stop";
  document.querySelector("#colorTarget").textContent = formatColorTarget(status.color_target);
  document.querySelector("#trackingTargetState").textContent = formatTrackingTarget(
    status.tracking_target,
  );
  document.querySelector("#cameraState").textContent = formatCamera(status.camera);
  document.querySelector("#rawStatus").textContent = JSON.stringify(status, null, 2);
  document.querySelector("#updatedAt").textContent = formatUpdatedAt(status.updated_at);

  const emergencyBtn = document.querySelector("#emergencyBtn");
  emergencyBtn.textContent = state.emergency ? "解除急停" : "急停";
  emergencyBtn.classList.toggle("is-active", state.emergency);

  if (typeof status.speed_scale === "number") {
    document.querySelector("#speedValue").textContent = `${Math.round(status.speed_scale * 100)}%`;
    speedScale.value = status.speed_scale;
  }
  if (!state.colorConfigDirty && status.color_config) {
    renderColorConfig(status.color_config);
  } else if (!state.colorConfigDirty && status.color_target?.hsv_low && status.color_target?.hsv_high) {
    renderColorConfig({
      name: status.color_target.name || state.colorConfig.name || "custom",
      hsv_low: status.color_target.hsv_low,
      hsv_high: status.color_target.hsv_high,
    });
  }

  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });

  renderSafety(status);
  renderManualLock();
  renderModeContext(mode);
  renderNodes(status.nodes || {});
  drawRadar(status.radar_points || []);
}

function formatTrackingTarget(target) {
  if (!target) return "自动搜索";
  if (target.locked) return `已锁定 ID ${target.track_id}`;
  if (target.selection_mode === "manual" && target.state === "selecting") return "等待点选命中";
  if (target.selection_mode === "manual") return "目标丢失，等待重选";
  return "自动搜索";
}

function imageClickPoint(event, image) {
  const rect = image.getBoundingClientRect();
  const naturalWidth = Math.max(1, image.naturalWidth || rect.width);
  const naturalHeight = Math.max(1, image.naturalHeight || rect.height);
  const scale = Math.max(rect.width / naturalWidth, rect.height / naturalHeight);
  const displayedWidth = naturalWidth * scale;
  const displayedHeight = naturalHeight * scale;
  const cropX = (displayedWidth - rect.width) / 2;
  const cropY = (displayedHeight - rect.height) / 2;
  return {
    x: Math.max(0, Math.min(1, (event.clientX - rect.left + cropX) / displayedWidth)),
    y: Math.max(0, Math.min(1, (event.clientY - rect.top + cropY) / displayedHeight)),
  };
}

function renderSafety(status) {
  const distance = Number(status.front_distance);
  const hasNearObstacle = Number.isFinite(distance) && distance > 0 && distance < 0.35;
  if (state.emergency) {
    document.querySelector("#safetyState").textContent = "急停锁定";
    showAlert("急停已触发", "当前不会放行底盘输出，解除前请确认小车处于安全状态。", "danger");
    return;
  }
  if (hasNearObstacle) {
    document.querySelector("#safetyState").textContent = "近障告警";
    showAlert("前方距离过近", `雷达前方距离约 ${distance.toFixed(2)} m，建议停车检查。`, "warning");
    return;
  }
  document.querySelector("#safetyState").textContent = "正常";
  alertBanner.hidden = true;
}

function renderManualLock() {
  const ready = state.lastMode === "manual" && !state.emergency;
  document.querySelector("#manualLock").textContent = ready ? "遥控已解锁" : "需 manual 且非急停";
  document.querySelector("#manualLock").classList.toggle("ready", ready);
  remotePanel.classList.toggle("is-locked", !ready);
  remotePanel.closest(".panel").classList.toggle("is-emphasis", state.lastMode === "manual");
}

function renderModeContext(mode) {
  const context = modeContexts[mode] || modeContexts.stop;
  document.body.dataset.mode = mode;
  document.querySelector("#modeContextTitle").textContent = context.title;
  document.querySelector("#modeContextText").textContent = context.text;
  document.querySelector("#modeContextChip").textContent = mode;
  const steps = document.querySelector("#modeContextSteps");
  steps.replaceChildren();
  context.steps.forEach((step) => {
    const item = document.createElement("span");
    item.textContent = step;
    steps.appendChild(item);
  });
  document.querySelector("#colorPanel").classList.toggle("is-hidden", mode !== "color_track");
  document.querySelector(".video-panel").classList.toggle("is-vision-mode", ["auto", "color_track", "object_follow"].includes(mode));
}

function renderNodes(nodes) {
  const entries = Object.entries(nodes);
  const okCount = entries.filter(([, value]) => value === true || value === "ok" || value?.ok === true).length;
  document.querySelector("#nodeSummary").textContent = entries.length ? `${okCount}/${entries.length}` : "--";
  const list = document.querySelector("#nodeList");
  list.replaceChildren();
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "node-item";
    empty.innerHTML = "<span>暂无节点心跳数据</span><i class=\"dot warn\"></i>";
    list.appendChild(empty);
    return;
  }
  for (const [name, value] of entries) {
    const ok = value === true || value === "ok" || value?.ok === true;
    const warn = value === "degraded" || value?.level === "warn";
    const item = document.createElement("div");
    item.className = "node-item";
    const label = document.createElement("span");
    label.textContent = name;
    const dot = document.createElement("i");
    dot.className = `dot ${ok ? "" : warn ? "warn" : "off"}`.trim();
    item.append(label, dot);
    list.appendChild(item);
  }
}

function setColorInputs(config) {
  const low = config.hsv_low || colorPresets.green.hsv_low;
  const high = config.hsv_high || colorPresets.green.hsv_high;
  document.querySelector("#hLow").value = low[0];
  document.querySelector("#sLow").value = low[1];
  document.querySelector("#vLow").value = low[2];
  document.querySelector("#hHigh").value = high[0];
  document.querySelector("#sHigh").value = high[1];
  document.querySelector("#vHigh").value = high[2];
  document.querySelector("#colorConfigName").textContent = formatColorName(config.name || "custom");
}

function readColorInputs() {
  const matchedPreset = document.querySelector("#colorPresets button.active")?.dataset.color;
  return {
    name: matchedPreset || "custom",
    hsv_low: [
      readNumber("#hLow", 0, 179),
      readNumber("#sLow", 0, 255),
      readNumber("#vLow", 0, 255),
    ],
    hsv_high: [
      readNumber("#hHigh", 0, 179),
      readNumber("#sHigh", 0, 255),
      readNumber("#vHigh", 0, 255),
    ],
  };
}

function readNumber(selector, min, max) {
  const value = Number(document.querySelector(selector).value);
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.max(min, Math.min(max, Math.round(value)));
}

function normalizeSpeedScale(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return 1;
  }
  return Math.max(MIN_SPEED_SCALE, Math.min(1, number));
}

function renderColorConfig(config) {
  state.colorConfig = config;
  document.querySelector("#colorConfigName").textContent = formatColorName(config.name || "custom");
  document.querySelector("#colorConfigValue").textContent = `${formatColorName(config.name || "custom")} ${formatHsv(config)}`;
  renderColorPresetSelection(config.name);
}

function renderColorPresetSelection(name) {
  document.querySelectorAll("#colorPresets button").forEach((button) => {
    button.classList.toggle("active", button.dataset.color === name);
  });
}

function showAlert(title, message, tone) {
  document.querySelector("#alertTitle").textContent = title;
  document.querySelector("#alertMessage").textContent = message;
  alertBanner.classList.toggle("is-danger", tone === "danger");
  alertBanner.hidden = false;
}

function formatDistance(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "--";
  }
  return `${Number(value).toFixed(2)} m`;
}

function formatColorTarget(value) {
  if (!value) {
    return "--";
  }
  if (typeof value === "string") {
    return value;
  }
  if (value.found != null) {
    return value.found ? `visible ${value.offset ?? ""}` : "lost";
  }
  if (value.name) {
    return value.name;
  }
  if (value.visible != null) {
    return value.visible ? "visible" : "lost";
  }
  return "detected";
}

function formatCamera(camera) {
  if (!camera) {
    return "--";
  }
  if (typeof camera === "string") {
    return camera;
  }
  if (camera.ok === true) {
    return "摄像头正常";
  }
  return camera.message || "未就绪";
}

function formatUpdatedAt(timestamp) {
  if (!timestamp) {
    return "等待状态同步";
  }
  const date = new Date(Number(timestamp) * 1000);
  if (Number.isNaN(date.getTime())) {
    return "状态时间未知";
  }
  return `状态更新 ${date.toLocaleTimeString("zh-CN", { hour12: false })}`;
}

function formatColorName(name) {
  return colorPresets[name]?.label || name || "custom";
}

function formatHsv(config) {
  if (!config?.hsv_low || !config?.hsv_high) {
    return "--";
  }
  return `${config.hsv_low.join(",")} / ${config.hsv_high.join(",")}`;
}

function drawRadar(points) {
  const canvas = document.querySelector("#radarCanvas");
  const countLabel = document.querySelector("#radarPointCount");
  if (!canvas || !countLabel) {
    return;
  }
  countLabel.textContent = points.length ? `${points.length} 点` : "等待 /scan";
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const originX = width / 2;
  const originY = height - 34;
  const scale = 58;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#07111f";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(56, 189, 248, 0.22)";
  ctx.lineWidth = 1;
  for (let radius = scale; radius <= scale * 4; radius += scale) {
    ctx.beginPath();
    ctx.arc(originX, originY, radius, Math.PI, 2 * Math.PI);
    ctx.stroke();
  }
  for (let degree = 0; degree <= 180; degree += 30) {
    const angle = (degree * Math.PI) / 180;
    ctx.beginPath();
    ctx.moveTo(originX, originY);
    ctx.lineTo(originX + Math.cos(Math.PI - angle) * scale * 4, originY - Math.sin(angle) * scale * 4);
    ctx.stroke();
  }
  ctx.fillStyle = "#38bdf8";
  for (const point of points) {
    const x = originX + Number(point.y || 0) * scale;
    const y = originY - Number(point.x || 0) * scale;
    if (x < 0 || x > width || y < 0 || y > height) {
      continue;
    }
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.fillStyle = "#22c55e";
  ctx.beginPath();
  ctx.moveTo(originX, originY - 12);
  ctx.lineTo(originX - 9, originY + 9);
  ctx.lineTo(originX + 9, originY + 9);
  ctx.closePath();
  ctx.fill();
}

function drawRadar(points) {
  const canvas = document.querySelector("#radarCanvas");
  const countLabel = document.querySelector("#radarPointCount");
  if (!canvas || !countLabel) {
    return;
  }
  countLabel.textContent = points.length ? `${points.length} pts` : "waiting /scan";
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const originX = width / 2;
  const originY = height - 42;
  const validDistances = points.map((point) => Number(point.distance || 0)).filter(Number.isFinite);
  const maxDistance = Math.max(4, ...validDistances);
  const radiusMax = Math.min(width * 0.44, height - 58);
  const scale = radiusMax / maxDistance;

  ctx.clearRect(0, 0, width, height);
  const background = ctx.createLinearGradient(0, 0, 0, height);
  background.addColorStop(0, "#0b1f3a");
  background.addColorStop(1, "#06101f");
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, width, height);

  ctx.save();
  ctx.shadowColor = "rgba(56, 189, 248, 0.55)";
  ctx.shadowBlur = 18;
  ctx.strokeStyle = "rgba(56, 189, 248, 0.28)";
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei, Segoe UI, sans-serif";
  for (let ring = 1; ring <= 4; ring += 1) {
    const radius = (radiusMax / 4) * ring;
    ctx.beginPath();
    ctx.arc(originX, originY, radius, Math.PI, 2 * Math.PI);
    ctx.stroke();
    ctx.fillStyle = "rgba(202, 240, 255, 0.58)";
    ctx.fillText(`${Math.round((maxDistance / 4) * ring)}m`, originX + radius + 4, originY - 5);
  }
  for (let degree = 0; degree <= 180; degree += 30) {
    const angle = (degree * Math.PI) / 180;
    ctx.beginPath();
    ctx.moveTo(originX, originY);
    ctx.lineTo(originX + Math.cos(Math.PI - angle) * radiusMax, originY - Math.sin(angle) * radiusMax);
    ctx.stroke();
  }
  ctx.restore();

  if (!points.length) {
    ctx.fillStyle = "rgba(202, 240, 255, 0.72)";
    ctx.font = "700 18px Microsoft YaHei, Segoe UI, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Waiting for /scan", originX, height * 0.46);
    ctx.font = "12px Microsoft YaHei, Segoe UI, sans-serif";
    ctx.fillText("LaserScan points will refresh here in real time.", originX, height * 0.46 + 24);
    ctx.textAlign = "start";
  }

  const sweep = ctx.createLinearGradient(originX, originY, originX, 20);
  sweep.addColorStop(0, "rgba(56, 189, 248, 0)");
  sweep.addColorStop(1, "rgba(56, 189, 248, 0.2)");
  ctx.fillStyle = sweep;
  ctx.beginPath();
  ctx.moveTo(originX, originY);
  ctx.arc(originX, originY, radiusMax, Math.PI * 1.18, Math.PI * 1.42);
  ctx.closePath();
  ctx.fill();

  ctx.fillStyle = "#67e8f9";
  ctx.shadowColor = "rgba(103, 232, 249, 0.9)";
  ctx.shadowBlur = 8;
  for (const point of points) {
    const x = originX + Number(point.y || 0) * scale;
    const y = originY - Number(point.x || 0) * scale;
    if (x < 0 || x > width || y < 0 || y > height) {
      continue;
    }
    ctx.beginPath();
    ctx.arc(x, y, 2.6, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.shadowBlur = 0;
  ctx.fillStyle = "#38bdf8";
  ctx.beginPath();
  ctx.moveTo(originX, originY - 12);
  ctx.lineTo(originX - 9, originY + 9);
  ctx.lineTo(originX + 9, originY + 9);
  ctx.closePath();
  ctx.fill();
}

function setFeedback(message, type = "") {
  modeFeedback.textContent = message;
  modeFeedback.classList.toggle("is-ok", type === "ok");
  modeFeedback.classList.toggle("is-error", type === "error");
}

function setVideoMessage(message, hidden) {
  videoOverlay.classList.toggle("is-hidden", hidden);
  if (hidden) {
    videoFeed.classList.remove("is-broken");
  }
  if (!hidden) {
    videoOverlay.querySelector("strong").textContent = message;
    videoOverlay.querySelector("span").textContent =
      "stop/manual 模式通常可网页预览；auto/object_follow/color_track 模式下视觉节点可能会占用摄像头。";
  }
}

function reloadVideo() {
  setVideoMessage("摄像头重连中", false);
  videoFeed.classList.remove("is-broken");
  videoFeed.src = `/video_feed?ts=${Date.now()}`;
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/app/service-worker.js").catch(console.warn);
}

async function initialize() {
  await applySavedColor();
  await applyDefaultSpeed();
  connectControl();
  connectStatus();
  reloadVideo();
}

initialize();
