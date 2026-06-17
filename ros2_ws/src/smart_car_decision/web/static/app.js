const modes = [
  ["stop", "停止", "车辆保持静止，适合调试和待机"],
  ["manual", "手动", "允许网页方向键发布 /manual_cmd"],
  ["auto", "自动避障", "融合雷达安全策略进行自动行驶"],
  ["mapping", "建图", "交给厂商 SLAM 链路，不直接发布速度"],
  ["navigation", "导航", "交给 Nav2 链路，不抢占 /cmd_vel"],
  ["color_track", "颜色追踪", "HSV 目标追踪并输出偏移量"],
  ["object_follow", "目标跟随", "YOLO 目标偏移转为跟随控制"],
];

const modeMap = new Map(modes.map(([value, label, description]) => [value, { label, description }]));
const modeButtons = document.querySelector("#modeButtons");
const modeFeedback = document.querySelector("#modeFeedback");
const videoFeed = document.querySelector("#videoFeed");
const videoOverlay = document.querySelector("#videoOverlay");
const remotePanel = document.querySelector(".remote");
const alertBanner = document.querySelector("#alertBanner");
const speedScale = document.querySelector("#speedScale");
const speedDefaultHint = document.querySelector("#speedDefaultHint");
const DEFAULT_SPEED_KEY = "smart-car-default-speed";

const state = {
  emergency: false,
  pollingTimer: null,
  websocket: null,
  controlSocket: null,
  controlSocketReady: false,
  lastMode: "stop",
  activeCommand: "",
  commandTimer: null,
};

for (const [value, label, description] of modes) {
  const button = document.createElement("button");
  button.textContent = label;
  button.title = description;
  button.dataset.mode = value;
  button.type = "button";
  button.addEventListener("click", () => setMode(value, label));
  modeButtons.appendChild(button);
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
  const scale = Number(event.target.value);
  document.querySelector("#speedValue").textContent = `${Math.round(scale * 100)}%`;
  try {
    await postJson("/api/speed", { scale });
  } catch (error) {
    setFeedback(error.message, "error");
  }
});

document.querySelector("#saveSpeedBtn").addEventListener("click", () => {
  const scale = Number(speedScale.value);
  localStorage.setItem(DEFAULT_SPEED_KEY, String(scale));
  renderDefaultSpeedHint(scale, true);
});

document.querySelector("#reloadVideoBtn").addEventListener("click", reloadVideo);
videoFeed.addEventListener("load", () => setVideoMessage("", true));
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
  const scale = Number.isFinite(saved) ? Math.max(0, Math.min(1, saved)) : 1;
  speedScale.value = scale;
  document.querySelector("#speedValue").textContent = `${Math.round(scale * 100)}%`;
  renderDefaultSpeedHint(scale, false);
  try {
    await postJson("/api/speed", { scale });
  } catch (error) {
    setFeedback(error.message, "error");
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

  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });

  renderSafety(status);
  renderManualLock();
  renderNodes(status.nodes || {});
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
}

function renderNodes(nodes) {
  const entries = Object.entries(nodes);
  const okCount = entries.filter(([, value]) => value === true || value?.ok === true).length;
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
    const ok = value === true || value?.ok === true;
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
    return "正常";
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

applyDefaultSpeed();
connectControl();
connectStatus();
reloadVideo();
