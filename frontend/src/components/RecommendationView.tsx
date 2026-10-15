import { useState } from "react";
import { dateTime, inr, pct } from "../format";
import type { RankedOffer, Recommendation } from "../types";
import { Badge, Card, Empty, Icon, SourceBadge } from "./ui";

// Weights are the backend's (README). Shown for transparency, never recomputed here.
const CRITERIA: { key: "cost" | "delivery" | "reliability" | "improvement"; label: string; weight: string }[] = [
  { key: "cost", label: "Landed cost", weight: "50%" },
  { key: "delivery", label: "Delivery", weight: "20%" },
  { key: "reliability", label: "Reliability", weight: "15%" },
  { key: "improvement", label: "Negotiated improvement", weight: "15%" },
];

function Breakdown({ offer }: { offer: RankedOffer }) {
  return (
    <div className="breakdown">
      {CRITERIA.map((c) => {
        const v = offer.breakdown[c.key];
        return (
          <div key={c.key} className="bd-row">
            <span>{c.label} <span className="muted">· {c.weight}</span></span>
            <div className="bar" aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(100, v ?? 0))}%` }} /></div>
            <span className="num">{v === undefined ? "Missing" : v.toFixed(1)}</span>
          </div>
        );
      })}
    </div>
  );
}

export function RecommendationView({ rec, onSupplier, status }: {
  rec: Recommendation | null; onSupplier: (companyId: string) => void; status: string;
}) {
  const [showRejected, setShowRejected] = useState(true);
  if (!rec) {
    return (
      <Empty title={status === "completed" ? "No recommendation stored" : "Recommendation not ready"}>
        {status === "draft"
          ? "Start the negotiation. The recommendation is produced after the final round."
          : "It is produced by the backend after the final round."}
      </Empty>
    );
  }
  const [top, ...rest] = rec.ranked;
  return (
    <div className="rec">
      {top ? (
        <Card className="rec-hero" title={<span className="rec-title"><Badge tone="ok">Recommended</Badge> {top.name}</span>}
          subtitle={top.explanation}
          actions={<button className="btn btn-ghost btn-sm" onClick={() => onSupplier(top.company_id)}>View evidence</button>}>
          <div className="rec-stats">
            <div><span className="label">Total landed cost</span><span className="value">{inr(top.landed_cost)}</span></div>
            <div><span className="label">Delivery</span><span className="value">{top.lead_time_days != null ? `${top.lead_time_days} days` : "—"}</span></div>
            <div><span className="label">Negotiated vs opening</span><span className="value">{top.improvement_pct != null ? pct(top.improvement_pct) : "—"}</span></div>
            <div><span className="label">Overall score</span><span className="value">{top.total_score?.toFixed(2) ?? "—"}</span></div>
          </div>
          <Breakdown offer={top} />
          <div className="badges">
            <span className="muted">Line sources:</span>
            {Object.entries(top.line_sources ?? {}).map(([mpn, s]) => (
              <span key={mpn} className="src-pair"><span className="mono">{mpn}</span><SourceBadge source={s} /></span>
            ))}
          </div>
          {top.flags.length > 0 && <ul className="reasons">{top.flags.map((f) => <li key={f}>{f}</li>)}</ul>}
          <p className="note">This is a recommendation, not a purchase. Nothing is ordered or committed from this screen.</p>
        </Card>
      ) : (
        <Empty title="No eligible supplier">Every supplier failed at least one mandatory constraint. See the reasons below.</Empty>
      )}

      {rest.length > 0 && (
        <Card title="Other eligible offers" subtitle="Ranked by the backend's weighted score">
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                <th>#</th><th>Supplier</th><th className="num">Landed cost</th><th className="num">Lead</th>
                {CRITERIA.map((c) => <th key={c.key} className="num">{c.label}</th>)}
                <th className="num">Score</th><th>Source</th>
              </tr></thead>
              <tbody>
                {rest.map((o, i) => (
                  <tr key={o.company_id} className="clickable" onClick={() => onSupplier(o.company_id)}>
                    <td>{i + 2}</td>
                    <td><div className="cell-main">{o.name}</div><div className="cell-sub">{o.explanation}</div></td>
                    <td className="num">{inr(o.landed_cost)}</td>
                    <td className="num">{o.lead_time_days ?? "—"} d</td>
                    {CRITERIA.map((c) => <td key={c.key} className="num">{o.breakdown[c.key]?.toFixed(1) ?? "Missing"}</td>)}
                    <td className="num strong">{o.total_score?.toFixed(2)}</td>
                    <td><SourceBadge source={o.source} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card title={`Not eligible (${rec.rejected.length})`}
        subtitle="A low price does not make an offer eligible when a mandatory constraint fails."
        actions={rec.rejected.length > 0 && (
          <button className="btn btn-ghost btn-sm" onClick={() => setShowRejected((v) => !v)} aria-expanded={showRejected}>
            {showRejected ? "Hide" : "Show"}
          </button>
        )}>
        {rec.rejected.length === 0 ? <p className="muted">Every invited supplier met the mandatory constraints.</p> : showRejected && (
          <ul className="rejected">
            {rec.rejected.map((o) => (
              <li key={o.company_id}>
                <div className="rej-head">
                  <strong>{o.name}</strong>
                  <span className="muted">landed {inr(o.landed_cost)}</span>
                  <button className="link" onClick={() => onSupplier(o.company_id)}>Evidence <Icon name="chevron" size={12} /></button>
                </div>
                <ul className="reasons">{o.eligibility_failures.map((f) => <li key={f}>{f}</li>)}</ul>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <p className="cell-sub">Generated {dateTime(rec.created_at)} · {rec.explanation}</p>
    </div>
  );
}
