import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { CameraStreamProvider, useCameraStream } from "../src/hooks/useCameraStream";

function View({ title }: { title: string }) {
  const { host, state, reconnect } = useCameraStream(true);
  return <section><h2>{title}</h2><div ref={host} style={{ width: 400, height: 225 }} /><p>{state}</p><button onClick={reconnect}>重连</button></section>;
}
function Harness() {
  const [page, setPage] = useState("主页");
  return <><button onClick={() => setPage(page === "主页" ? "实操" : "主页")}>切换</button>
    <CameraStreamProvider><View key={page} title={page} /></CameraStreamProvider></>;
}
createRoot(document.getElementById("root")!).render(<StrictMode><Harness /></StrictMode>);
