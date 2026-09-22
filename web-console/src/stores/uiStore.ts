import { createStore } from "../lib/store";

export type MapLayerKey = "occupancy" | "robot" | "lidar" | "route" | "incident";

type UiState = {
  selectedRobotId: string | null;
  mapLayers: Record<MapLayerKey, boolean>;
  commandOpen: boolean;
  notificationsOpen: boolean;
  userMenuOpen: boolean;
  navOpen: string | null;
};

const initial: UiState = {
  selectedRobotId: null,
  mapLayers: { occupancy: true, robot: true, lidar: true, route: true, incident: true },
  commandOpen: false,
  notificationsOpen: false,
  userMenuOpen: false,
  navOpen: null,
};

export const uiStore = createStore<UiState>(initial);
