import { useLayoutEffect, useRef } from "react";
import { Send, Square } from "lucide-react";
import { shouldSendWithEnter } from "./chatState";

export const suggestions = ["查看机器人状态", "最近有哪些异常？", "帮我规划巡检任务"];

export function AssistantComposer({input, change, send, stop, generating, disabled, visible}: {
  input: string; change: (value: string) => void; send: () => void; stop: () => void;
  generating: boolean; disabled: boolean; visible: boolean;
}) {
  const field = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  useLayoutEffect(() => {
    if (!visible || CSS.supports("field-sizing", "content")) return;
    const textarea = field.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(104, textarea.scrollHeight + 2)}px`;
  }, [input, visible]);
  return <form className="assistant-composer" onSubmit={event => {
    event.preventDefault();
    if (!disabled && !generating && !composing.current && input.trim()) send();
  }}>
    <div className="assistant-input-row">
      <textarea ref={field} data-assistant-input aria-label="发送给智巡助手的消息" placeholder="输入消息…" maxLength={2000}
        value={input} onChange={event => change(event.target.value)} rows={1}
        onCompositionStart={() => { composing.current = true; }}
        onCompositionEnd={() => { composing.current = false; }}
        onKeyDown={event => {
          if (shouldSendWithEnter(event.key, event.shiftKey, composing.current || event.nativeEvent.isComposing, event.keyCode)) {
            event.preventDefault();
            if (!event.repeat) event.currentTarget.form?.requestSubmit();
          }
        }} />
      {generating ? <button type="button" className="assistant-send" aria-label="停止回复" title="停止回复" onClick={stop}>
        <Square size={16} />
      </button> : <button type="submit" className="assistant-send" aria-label="发送" title="发送"
        disabled={disabled || !input.trim()}><Send size={17} /></button>}
    </div>
    <small>Enter 发送 · Shift + Enter 换行</small>
  </form>;
}
