import { useSyncExternalStore } from "react";
import { getBusinessSession, subscribeBusinessSession } from "../services/businessApi";

export function useBusinessSession() {
  return useSyncExternalStore(subscribeBusinessSession, getBusinessSession);
}
