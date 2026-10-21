import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { CameraStreamProvider } from "./hooks/useCameraStream";
import { RobotStreamProvider } from "./hooks/useRobotStream";
import "./styles/insight.css";
import "./styles/live.css";
import "./styles/navigation.css";
import "./styles/maps.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RobotStreamProvider><CameraStreamProvider><App /></CameraStreamProvider></RobotStreamProvider>
  </React.StrictMode>
);
