import { useCallback, useEffect, useRef, useState } from "react";
import { businessApi, createMapRequestId, streamAssistantMessage, type AssistantSession } from "../../services/businessApi";
import { applyChatEvent, mergeAssistantTurns, type ChatTurn } from "./chatState";

const empty: ChatTurn[] = [];
const errorText = (error: unknown) => error instanceof Error ? error.message : "暂时无法连接助手";

function savedSession(key: string) {
  try { return localStorage.getItem(key); }
  catch { return null; }
}

export function useAssistantChat(userId: string, floating: boolean, visible: boolean, onReply?: (id: string) => void) {
  const storageKey = `insightrover.assistant-session.${userId}`;
  const [sessionId, setSessionId] = useState<string | null>(() => floating ? savedSession(storageKey) : null);
  const [sessions, setSessions] = useState<AssistantSession[]>([]);
  const [bySession, setBySession] = useState<Record<string, ChatTurn[]>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [creating, setCreating] = useState(false);
  const [listError, setListError] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [reload, setReload] = useState(0);
  const requests = useRef(new Map<string, AbortController>());
  const creatingRequest = useRef<AbortController>(null);
  const initialSelection = useRef(true);
  const onReplyRef = useRef(onReply);
  useEffect(() => { onReplyRef.current = onReply; }, [onReply]);
  const draftKey = sessionId ?? "";
  const input = drafts[draftKey] ?? "";
  const turns = sessionId ? bySession[sessionId] ?? empty : empty;
  const generating = turns.some(turn => turn.generation?.state === "generating" || turn.generation?.state === "using_tools");

  function changeTurns(id: string, change: (turns: ChatTurn[]) => ChatTurn[]) {
    setBySession(current => ({...current, [id]: change(current[id] ?? empty)}));
  }

  function setError(id: string, message: string) {
    setErrors(current => ({...current, [id]: message}));
  }

  useEffect(() => {
    const active = requests.current;
    return () => {
      creatingRequest.current?.abort();
      active.forEach(controller => controller.abort());
      active.clear();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    businessApi.assistantSessions(controller.signal).then(({items}) => {
      if (controller.signal.aborted) return;
      setSessions(current => {
        const ids = new Set(items.map(item => item.id));
        return [...current.filter(item => !ids.has(item.id)), ...items];
      });
      if (initialSelection.current) {
        initialSelection.current = false;
        setSessionId(current => current ?? items[0]?.id ?? null);
      }
    }).catch(error => {
      if (!controller.signal.aborted) setListError(errorText(error));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [reload]);

  useEffect(() => {
    if (!floating || loading) return;
    try {
      if (sessionId) localStorage.setItem(storageKey, sessionId);
      else localStorage.removeItem(storageKey);
    } catch { /* Storage is optional. */ }
  }, [floating, loading, sessionId, storageKey]);

  useEffect(() => {
    if (!sessionId || !visible) return;
    const id = sessionId;
    const controller = new AbortController();
    setLoadingMessages(true);
    setError(id, "");
    businessApi.assistantMessages(id, controller.signal).then(result => {
      if (!controller.signal.aborted) changeTurns(id, current => mergeAssistantTurns(result.items, current));
    }).catch(error => {
      if (!controller.signal.aborted) setError(id, errorText(error));
    }).finally(() => {
      if (!controller.signal.aborted) setLoadingMessages(false);
    });
    return () => controller.abort();
  }, [sessionId, visible, reload]);

  function setInput(text: string) {
    setDrafts(current => ({...current, [draftKey]: text}));
  }

  function select(id: string | null) {
    if (creatingRequest.current) return;
    initialSelection.current = false;
    setSessionId(id);
  }

  const refresh = useCallback(() => {
    setListError("");
    setReload(value => value + 1);
  }, []);

  async function send(text: string, retry?: ChatTurn) {
    text = text.trim();
    if (!text || creatingRequest.current || (sessionId && requests.current.has(sessionId))) return;
    const controller = new AbortController();
    let id = sessionId;
    if (!id) {
      creatingRequest.current = controller;
      setCreating(true);
      setError("", "");
      try {
        const created = await businessApi.createAssistantSession(controller.signal);
        if (controller.signal.aborted) return;
        id = created.id;
        setSessionId(id);
        setSessions(items => [{id: created.id, created_at: new Date().toISOString(), title: text.slice(0, 64)}, ...items]);
      } catch (error) {
        if (!controller.signal.aborted) setError("", errorText(error));
        return;
      } finally {
        creatingRequest.current = null;
        if (!controller.signal.aborted) setCreating(false);
      }
    }
    const target = id;
    const clientId = retry?.client_id ?? createMapRequestId();
    const pending: ChatTurn = {id: clientId, client_id: clientId, text, reply: null,
      generation: {state: "generating", text: "", tools: []}};
    requests.current.set(target, controller);
    if (!retry) setInput("");
    setError(target, "");
    setSessions(items => items.map(item => item.id === target && !item.title ? {...item, title: text.slice(0, 64)} : item));
    changeTurns(target, current => retry
      ? current.map(turn => turn.client_id === clientId ? pending : turn) : [...current, pending]);

    function update(change: (turn: ChatTurn) => ChatTurn) {
      if (requests.current.get(target) === controller) {
        changeTurns(target, current => current.map(turn => turn.client_id === clientId ? change(turn) : turn));
      }
    }
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(100000)]);
    try {
      const turn = await streamAssistantMessage(target, clientId, text, event => update(item => applyChatEvent(item, event)), signal);
      update(() => turn);
      if (!controller.signal.aborted) onReplyRef.current?.(target);
    } catch (error) {
      update(turn => turn.generation ? {...turn, generation: {...turn.generation,
        state: controller.signal.aborted ? "cancelled" : "failed",
        error: controller.signal.aborted ? undefined : errorText(error)}} : turn);
      if (!controller.signal.aborted) onReplyRef.current?.(target);
    } finally {
      if (requests.current.get(target) === controller) requests.current.delete(target);
    }
  }

  return {
    sessionId, select, sessions, turns, input, setInput, send, generating, creating,
    loading: loading || (sessionId !== null && loadingMessages),
    error: errors[draftKey] || listError,
    refresh,
    stop: () => { if (sessionId) requests.current.get(sessionId)?.abort(); },
  };
}
