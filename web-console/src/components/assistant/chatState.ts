import type { AssistantChatEvent, AssistantExecution, AssistantTool, AssistantTurn } from "../../services/businessApi";

export type Generation = {
  state: "generating" | "using_tools" | "failed" | "cancelled";
  text: string;
  tools: AssistantTool[];
  error?: string;
};
export type ChatTurn = AssistantTurn & { generation?: Generation };

export function applyChatEvent(turn: ChatTurn, event: AssistantChatEvent): ChatTurn {
  const generation = turn.generation;
  if (!generation || generation.state === "failed" || generation.state === "cancelled") return turn;
  switch (event.kind) {
    case "generating":
      return {...turn, generation: {...generation, state: "generating", text: ""}};
    case "delta":
      return {...turn, generation: {...generation, text: generation.text + event.text}};
    case "tool": {
      const {kind: _, ...tool} = event;
      const tools = [...generation.tools.filter(item => item.id !== tool.id), tool].sort((a, b) => a.id - b.id);
      return {...turn, generation: {state: "using_tools", text: "", tools}};
    }
    default:
      return turn;
  }
}

export function mergeAssistantTurns(saved: AssistantTurn[], local: ChatTurn[]): ChatTurn[] {
  const savedIds = new Set(saved.map(turn => turn.client_id));
  const byId = new Map(local.map(turn => [turn.client_id, turn]));
  return [...saved.map(turn => {
    const existing = byId.get(turn.client_id);
    if (!existing) return turn;
    if (!turn.reply) return existing;
    const incomingPlan = turn.reply.plan;
    const existingExecution = existing.reply?.plan?.execution;
    if (incomingPlan && existingExecution?.plan_id === incomingPlan.id &&
        existingExecution.version > (incomingPlan.execution?.version ?? 0)) {
      return {...turn, reply: {...turn.reply, plan: {...incomingPlan, state: "confirmed", execution: existingExecution}}};
    }
    return turn;
  }), ...local.filter(turn => !savedIds.has(turn.client_id))];
}

export function rememberExecution(executions: Record<string, AssistantExecution>, execution: AssistantExecution) {
  const existing = executions[execution.plan_id];
  return existing && existing.version >= execution.version ? executions : {...executions, [execution.plan_id]: execution};
}

export function currentPlan(turn: ChatTurn, executions: Record<string, AssistantExecution>) {
  const plan = turn.reply?.plan;
  const execution = plan && executions[plan.id];
  return plan && execution && execution.version > (plan.execution?.version ?? 0)
    ? {...plan, state: "confirmed", execution} : plan;
}

export function followsLatest(scrollTop: number, clientHeight: number, scrollHeight: number) {
  return scrollHeight - clientHeight - scrollTop <= 40;
}

export function shouldSendWithEnter(key: string, shift: boolean, composing: boolean, keyCode: number) {
  return key === "Enter" && !shift && !composing && keyCode !== 229;
}
