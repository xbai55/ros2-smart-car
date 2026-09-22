import { useState } from "react";
import { useData } from "../hooks/useData";
import { adapters } from "../services/adapters";
import { Badge, Panel } from "../components/ui";
import { DataTable, ObjectHeader, type Column } from "../components/shared";
import type { AssetItem } from "../types/domain";

const catLabel = (c: AssetItem["category"]) => (c === "device" ? "设备" : c === "model" ? "模型" : "媒体");

export function AssetsPage() {
  const { data, loading } = useData(() => adapters.listAssets());
  const [cat, setCat] = useState<AssetItem["category"] | "all">("all");
  const items = (data ?? []).filter((a) => cat === "all" || a.category === cat);

  const columns: Column<AssetItem>[] = [
    { key: "name", header: "资产", render: (a) => <div className="cell-strong"><strong>{a.name}</strong><em>{a.id}</em></div> },
    { key: "category", header: "类别", render: (a) => <Badge tone={a.category === "device" ? "blue" : a.category === "model" ? "info" : "neutral"}>{catLabel(a.category)}</Badge> },
    { key: "location", header: "位置/描述", render: (a) => a.location },
    { key: "updated", header: "更新时间", render: (a) => a.updatedAt },
    { key: "status", header: "状态", render: (a) => <Badge tone={a.status === "active" ? "success" : "neutral"}>{a.status === "active" ? "使用中" : "已归档"}</Badge> },
  ];

  return (
    <div className="page">
      <ObjectHeader kicker="Assets" title="业务资产" subtitle="设备、检测模型与现场媒体等业务资产入口" badges={[{ label: `${(data ?? []).length} 项资产`, tone: "blue" }]} />
      <Panel className="list-panel" bodyClassName="panel-flush">
        <div className="list-toolbar">
          <div className="filter-tabs">
            {(["all", "device", "model", "media"] as const).map((c) => (
              <button key={c} type="button" className={cat === c ? "on" : ""} onClick={() => setCat(c)}>{c === "all" ? "全部" : catLabel(c)}</button>
            ))}
          </div>
        </div>
        <DataTable columns={columns} rows={items} rowKey={(a) => a.id} loading={loading} emptyTitle="暂无资产" />
      </Panel>
    </div>
  );
}
