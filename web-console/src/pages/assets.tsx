import { EmptyState, Panel } from "../components/ui";
import { ObjectHeader } from "../components/shared";
export function AssetsPage() {
  return <div className="page"><ObjectHeader kicker="Assets" title="业务资产" subtitle="设备、模型与媒体登记"/><Panel title="资产清单"><EmptyState title="尚未接入资产登记" hint="当前没有可核实的资产清单和媒体记录。"/></Panel></div>;
}
