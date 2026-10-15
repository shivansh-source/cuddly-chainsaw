import { useMemo, useState } from "react";
import { inr, num, time } from "../format";
import type { Offer, Turn } from "../types";
import { Badge, ControllerBadge, Empty, GuardBadge, SourceBadge } from "./ui";

const ACTION_LABEL: Record<string, string> = {
  propose: "Proposed", counter: "Countered", trade: "Traded", ask: "Asked", accept: "Accepted", walk_away: "Walked away",
};

/** Chronological operational record of every move, with its validation result. */
export function Timeline({ turns, offers, name, suppliers, onEvidence }: {
  turns: Turn[]; offers: Offer[]; name: (id: string) => string; suppliers: string[];
  onEvidence?: (o: Offer) => void;
}) {
  const [who, setWho] = useState<string>("all");
  const [part, setPart] = useState<string>("all");
  const parts = useMemo(() => Array.from(new Set(turns.map((t) => t.mpn).filter(Boolean))).sort(), [turns]);
  const offerByTurn = useMemo(() => {
    const m = new Map<string, Offer>();
    for (const o of offers) if (!m.has(o.turn_id) || o.status !== "accepted") m.set(o.turn_id, o);
    return m;
  }, [offers]);

  const list = turns
    .filter((t) => who === "all" || t.participant_id === who || t.counterparty_id === who)
    .filter((t) => part === "all" || t.mpn === part || !t.mpn)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  if (!turns.length) return <Empty title="No moves yet">Turns appear here once the negotiation starts.</Empty>;

  return (
    <div>
      <div className="filters">
        {suppliers.length > 1 && (
          <label className="select-label">Supplier
            <select value={who} onChange={(e) => setWho(e.target.value)}>
              <option value="all">All suppliers</option>
              {suppliers.map((s) => <option key={s} value={s}>{name(s)}</option>)}
            </select>
          </label>
        )}
        {parts.length > 1 && (
          <label className="select-label">Part
            <select value={part} onChange={(e) => setPart(e.target.value)}>
              <option value="all">All parts</option>
              {parts.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
        )}
        <span className="muted">{list.length} of {turns.length} moves · newest first</span>
      </div>
      <ol className="timeline">
        {list.map((t) => {
          const g = t.guardrail_result ?? {};
          if (g.event === "controller_switch") {
            return (
              <li key={t.id} className="tl tl-system">
                <span className="tl-time">{time(t.created_at)}</span>
                <span><strong>{name(t.participant_id)}</strong> control switched from {g.from} to <strong>{g.to}</strong></span>
              </li>
            );
          }
          const a = t.validated_action;
          const offer = offerByTurn.get(t.id);
          const fellBack = t.notes?.includes("used deterministic fallback") && t.attempts > 0;
          return (
            <li key={t.id} className={`tl tl-${t.side}`}>
              <span className="tl-time">{time(t.created_at)}</span>
              <div className="tl-body">
                <div className="tl-head">
                  <strong>{name(t.participant_id)}</strong>
                  <span className="muted">{t.side === "buyer" ? "Buyer" : "Supplier"} → {name(t.counterparty_id)}</span>
                  <Badge>Round {t.round}</Badge>
                  <ControllerBadge controller={t.controller} />
                  <SourceBadge source={t.source} voiceMode={offer?.voice_mode} />
                  {t.channel === "voice" && <Badge tone="accent">Voice</Badge>}
                </div>
                <div className="tl-action">
                  <span>{a ? ACTION_LABEL[a.type] ?? a.type : "—"}</span>
                  {a?.mpn && <span className="mono">{a.mpn}</span>}
                  {a?.unit_price != null && <strong>{inr(a.unit_price)}</strong>}
                  {a?.qty != null && <span className="muted">× {num(a.qty)}</span>}
                  {a?.lead_time_days != null && <span className="muted">· {a.lead_time_days} d lead</span>}
                  <GuardBadge status={g.status} />
                </div>
                {t.message && <p className="tl-msg">“{t.message}”</p>}
                {g.reasons && g.reasons.length > 0 && <ul className="reasons">{g.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
                {fellBack && <p className="cell-sub">The model's answer did not pass the guardrail; the deterministic counter was used.</p>}
                {offer && onEvidence && (
                  <button className="link" onClick={() => onEvidence(offer)}>View evidence</button>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
