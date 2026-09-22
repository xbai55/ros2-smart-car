import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useData } from "../hooks/useData";
import { adapters } from "../services/adapters";
import { Panel } from "../components/ui";
import { BarChart, LineChart, ObjectHeader } from "../components/shared";

export function AnalyticsPage() {
  const { data, loading, refetch } = useData(() => adapters.getAnalytics());
  const [range, setRange] = useState("week");
  const stats = data;

  return (
    <div className="page">
      <ObjectHeader
        kicker="Analytics"
        title="数据洞察"
        subtitle="任务、异常与机器人运行的统计趋势与业务覆盖"
        actions={
          <>
            <div className="segmented">
              {(["week", "month"] as const).map((r) => (
                <button key={r} type="button" className={range === r ? "on" : ""} onClick={() => setRange(r)}>{r === "week" ? "本周" : "本月"}</button>
              ))}
            </div>
            <button type="button" className="btn btn-outline btn-sm" onClick={refetch}><RefreshCw size={14} />刷新</button>
          </>
        }
      />

      <div className="analytics-grid">
        <Panel title="任务趋势" kicker="Patrol · Transport" className="analytics-chart">
          {loading || !stats ? <div className="chart-placeholder">加载中…</div> : (
            <LineChart
              series={[
                { name: "巡检", color: "#2563eb", data: stats.patrolCount },
                { name: "运输", color: "#0ea5e9", data: stats.transportCount },
              ]}
              labels={stats.days}
            />
          )}
          <div className="chart-legend"><span><i style={{ background: "#2563eb" }} />巡检任务</span><span><i style={{ background: "#0ea5e9" }} />运输任务</span></div>
        </Panel>

        <Panel title="异常趋势" kicker="Incidents" className="analytics-chart">
          {loading || !stats ? <div className="chart-placeholder">加载中…</div> : <BarChart values={stats.incidentCount} labels={stats.days} color="#dc2626" />}
        </Panel>

        <Panel title="机器人利用率" kicker="Utilization %" className="analytics-chart">
          {loading || !stats ? <div className="chart-placeholder">加载中…</div> : <LineChart series={[{ name: "利用率", color: "#16a34a", data: stats.utilization }]} labels={stats.days} />}
        </Panel>

        <Panel title="巡检覆盖率" kicker="Coverage %" className="analytics-chart">
          {loading || !stats ? <div className="chart-placeholder">加载中…</div> : <LineChart series={[{ name: "覆盖率", color: "#7c3aed", data: stats.coverage }]} labels={stats.days} />}
        </Panel>
      </div>

      <div className="analytics-foot">
        <Panel title="统计摘要" kicker="Summary">
          <div className="stat-summary">
            <div><em>统计范围</em><strong>{range === "week" ? "本周" : "本月"}</strong></div>
            <div><em>巡检完成</em><strong>{stats ? stats.patrolCount.reduce((a, b) => a + b, 0) : 0}</strong></div>
            <div><em>运输完成</em><strong>{stats ? stats.transportCount.reduce((a, b) => a + b, 0) : 0}</strong></div>
            <div><em>异常总数</em><strong>{stats ? stats.incidentCount.reduce((a, b) => a + b, 0) : 0}</strong></div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
