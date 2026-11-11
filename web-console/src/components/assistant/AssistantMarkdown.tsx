import { Fragment, memo, type ReactNode } from "react";

export function safeAssistantLink(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch { return null; }
}

function inline(text: string): ReactNode[] {
  const tokens = /(\x60[^\x60\n]+\x60|\*\*[^*\n]+\*\*|\*[^*\n]+\*|!?\[[^\]\n]+\]\([^\s)]+\))/g;
  return text.split(tokens).map((token, index) => {
    if (index % 2 === 0) return token;
    if (token.startsWith("\x60")) return <code key={index}>{token.slice(1, -1)}</code>;
    if (token.startsWith("**")) return <strong key={index}>{token.slice(2, -2)}</strong>;
    if (token.startsWith("*")) return <em key={index}>{token.slice(1, -1)}</em>;
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
    const href = link && safeAssistantLink(link[2]);
    return href ? <a key={index} href={href} target="_blank" rel="noopener noreferrer">{link[1]}</a> : token;
  });
}

const heading = /^(#{1,6})\s+(.+)$/;
const listItem = /^(\s*[-+*]|\s*\d+\.)\s+(.+)$/;
const divider = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/;
const cells = (line: string) => line.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());

export const AssistantMarkdown = memo(function AssistantMarkdown({ text }: {text: string}) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  const beginsBlock = (index: number) => /^\s*(?:\x60{3}|>)/.test(lines[index]) || heading.test(lines[index]) ||
    listItem.test(lines[index]) || (lines[index].includes("|") && divider.test(lines[index + 1] ?? ""));
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    const key = i++;
    if (!line.trim()) continue;
    if (/^\s*\x60{3}/.test(line)) {
      const code = [];
      while (i < lines.length && !/^\s*\x60{3}\s*$/.test(lines[i])) code.push(lines[i++]);
      i++;
      blocks.push(<pre key={key}><code>{code.join("\n")}</code></pre>);
    } else if (line.includes("|") && divider.test(lines[i] ?? "")) {
      const headers = cells(line);
      const rows = [];
      i++;
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) rows.push(cells(lines[i++]));
      blocks.push(<div key={key} className="assistant-table"><table>
        <thead><tr>{headers.map((cell, index) => <th key={index} scope="col">{inline(cell)}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={index}>{headers.map((_, column) =>
          <td key={column}>{inline(row[column] ?? "")}</td>)}</tr>)}</tbody>
      </table></div>);
    } else if (heading.test(line)) {
      blocks.push(<p key={key} className="assistant-markdown-heading"><strong>{inline(line.replace(heading, "$2"))}</strong></p>);
    } else if (listItem.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const List = ordered ? "ol" : "ul";
      const items = [line.replace(listItem, "$2")];
      while (i < lines.length && listItem.test(lines[i]) && /^\s*\d/.test(lines[i]) === ordered) {
        items.push(lines[i++].replace(listItem, "$2"));
      }
      blocks.push(<List key={key}>{items.map((item, index) => <li key={index}>{inline(item)}</li>)}</List>);
    } else if (/^\s*>/.test(line)) {
      const quoted = [line.replace(/^\s*>\s?/, "")];
      while (i < lines.length && /^\s*>/.test(lines[i])) quoted.push(lines[i++].replace(/^\s*>\s?/, ""));
      blocks.push(<blockquote key={key}>{inline(quoted.join("\n"))}</blockquote>);
    } else {
      const paragraph = [line];
      while (i < lines.length && lines[i].trim() && !beginsBlock(i)) paragraph.push(lines[i++]);
      blocks.push(<p key={key}>{paragraph.map((part, index) =>
        <Fragment key={index}>{index > 0 && <br />}{inline(part)}</Fragment>)}</p>);
    }
  }
  return <div className="assistant-markdown">{blocks}</div>;
});
