import { Fragment, useState } from "react";
import { thread, type SupplierRow } from "../derive";
import { dateTime, inr, num, sourceLabel, STATUS_LABEL } from "../format";
import type { Offer, RankedOffer, Turn, VoiceCall } from "../types";
import { Badge, Drawer, GuardBadge, Icon, KV, SourceBadge, StatusBadge } from "./ui";

type Filter = "all" | "eligible" | "ineligible" | "pending";

/** Supplier comparison. Eligibility and ranking come only from the recommendation. */
export function OfferTable({ rows, name, reliability, ranked, rejected, onEvidence, showFilters }: {
  rows: SupplierRow[];
  name: (id: string) => string;
  reliability: (id: string) => number | undefined;
  ranked: RankedOffer[] | null;
  rejected: RankedOffer[] | null;
  onEvidence: (o: Offer) => void;
  showFilters: boolean;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const hasRec = ranked !== null;
  const recFor = (id: string) => ranked?.find((r) => r.company_id === id) ?? rejected?.find((r) => r.company_id === id);
  const leader = ranked?.[0]?.company_id ?? null;

  // Before a recommendation exists, point out only the cheapest *fully quoted*
  // supplier, and say plainly that eligibility is not yet decided.
  const fullyQuoted = rows.filter((r) => r.quotedLines === r.lines.length && r.landed !== null);
  const cheapest = !hasRec && fullyQuoted.length
    ? fullyQuoted.reduce((a, b) => (a.landed! <= b.landed! ? a : b)).supplier : null;

  const visible = rows.filter((r) => {
    const rec = recFor(r.supplier);
    if (filter === "eligible") return rec?.eligible === true;
    if (filter === "ineligible") return rec?.eligible === false;
    if (filter === "pending") return r.pendingFlags > 0;
    return true;
  });

  return (
    <div>
      {showFilters && (
        <div className="filters" role="group" aria-label="Filter offers">
          {(["all", "eligible", "ineligible", "pending"] as Filter[]).map((f) => (
            <button key={f} className={`chip ${filter === f ? "chip-on" : ""}`} onClick={() => setFilter(f)}
              disabled={(f === "eligible" || f === "ineligible") && !hasRec}>
              {f === "all" ? "All" : f === "eligible" ? "Eligible" : f === "ineligible" ? "Not eligible" : "Awaiting confirmation"}
            </button>
          ))}
        </div>
      )}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Supplier</th>
              <th className="num">Landed cost</th>
              <th className="num">Lead time</th>
              <th className="num">Reliability</th>
              <th className="num">Round</th>
              <th>Source</th>
              <th>Eligibility</th>
              <th aria-label="Details" />
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr><td colSpan={8} className="muted center">No suppliers match this filter.</td></tr>
            )}
            {visible.map((r) => {
              const rec = recFor(r.supplier);
              const isOpen = open === r.supplier;
              return (
                <Fragment key={r.supplier}>
                  <tr className={`${r.supplier === leader ? "row-lead" : ""} clickable`}
                    onClick={() => setOpen(isOpen ? null : r.supplier)}>
                    <td>
                      <div className="cell-main">{name(r.supplier)}</div>
                      <div className="cell-sub">
                        {r.quotedLines}/{r.lines.length} lines quoted
                        {r.allAgreed && " · all lines agreed"}
                        {r.pendingFlags > 0 && <> · <span className="warn-text">{r.pendingFlags} awaiting confirmation</span></>}
                      </div>
                    </td>
                    <td className="num strong">
                      {r.landed !== null ? inr(r.landed) : "—"}
                      {r.quotedLines > 0 && r.quotedLines < r.lines.length && <div className="cell-sub">partial</div>}
                    </td>
                    <td className="num">{r.lead !== null ? `${r.lead} d` : "—"}</td>
                    <td className="num">{reliability(r.supplier) ?? "—"}</td>
                    <td className="num">{r.round ?? "—"}</td>
                    <td><div className="badges">{r.sources.length ? r.sources.map((s) => <SourceBadge key={s} source={s} />) : <span className="muted">No offer</span>}</div></td>
                    <td>
                      {rec ? (
                        rec.eligible
                          ? <Badge tone="ok">{r.supplier === leader ? "Recommended" : "Eligible"}</Badge>
                          : <Badge tone="err" title={rec.eligibility_failures.join("\n")}>Not eligible</Badge>
                      ) : r.supplier === cheapest
                        ? <Badge tone="accent" title="Eligibility is decided when the negotiation completes">Lowest so far · pending</Badge>
                        : <span className="muted">Pending</span>}
                    </td>
                    <td className="chev"><span className={isOpen ? "rot" : ""}><Icon name="chevron" size={16} /></span></td>
                  </tr>
                  {isOpen && (
                    <tr className="row-detail">
                      <td colSpan={8}>
                        {rec && !rec.eligible && (
                          <div className="reason-box">
                            <strong>Why not eligible</strong>
                            <ul>{rec.eligibility_failures.map((f) => <li key={f}>{f}</li>)}</ul>
                          </div>
                        )}
                        <table className="table table-inner">
                          <thead>
                            <tr>
                              <th>Part</th><th className="num">Qty</th><th className="num">Opening</th>
                              <th className="num">Current</th><th className="num">Tax</th><th className="num">Shipping</th>
                              <th className="num">Landed</th><th className="num">Lead</th><th>Source</th><th>Status</th><th />
                            </tr>
                          </thead>
                          <tbody>
                            {r.lines.map((ln) => (
                              <tr key={ln.mpn}>
                                <td className="mono">{ln.mpn}</td>
                                <td className="num">{num(ln.current?.qty ?? ln.qty)}</td>
                                <td className="num muted">{inr(ln.opening?.unit_price)}</td>
                                <td className="num strong">{inr(ln.current?.unit_price)}</td>
                                <td className="num">{inr(ln.current?.tax)}</td>
                                <td className="num">{inr(ln.current?.shipping)}</td>
                                <td className="num">{inr(ln.current?.total_landed_cost)}</td>
                                <td className="num">{ln.current?.lead_time_days != null ? `${ln.current.lead_time_days} d` : "—"}</td>
                                <td>{ln.current ? <SourceBadge source={ln.current.source} voiceMode={ln.current.voice_mode} /> : "—"}</td>
                                <td>{ln.current ? <StatusBadge status={ln.current.status} /> : <span className="muted">No offer</span>}</td>
                                <td>{ln.current && (
                                  <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); onEvidence(ln.current!); }}>
                                    Evidence
                                  </button>
                                )}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <p className="cell-sub">Opening is the round-0 quote at the same quantity. Landed cost is the backend's figure: price × qty + tax + shipping.</p>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Everything behind one number: offer, revisions, turn, guardrail, voice call. */
export function EvidenceDrawer({ offer, offers, turns, calls, name, onClose }: {
  offer: Offer; offers: Offer[]; turns: Turn[]; calls: VoiceCall[]; name: (id: string) => string; onClose: () => void;
}) {
  const turn = turns.find((t) => t.id === offer.turn_id);
  const history = thread(offers, offer.company_id, offer.mpn).sort((a, b) => a.created_at.localeCompare(b.created_at));
  const call = offer.call_id ? calls.find((c) => c.id === offer.call_id) : undefined;
  const g = turn?.guardrail_result;

  return (
    <Drawer title={`Evidence · ${offer.mpn}`} subtitle={`${name(offer.company_id)} · round ${offer.round} · version ${offer.version}`} onClose={onClose}>
      <section className="ev-section">
        <h3>Offer</h3>
        <KV items={[
          ["Offer id", <span className="mono">{offer.id}</span>],
          ["Made by", `${offer.side === "seller" ? "Supplier" : "Buyer"} (${offer.created_by.split(":")[1] ? name(offer.created_by.split(":")[1]) : offer.created_by})`],
          ["Source", <SourceBadge source={offer.source} voiceMode={offer.voice_mode} />],
          ["Status", <StatusBadge status={offer.status} />],
          ["Unit price", inr(offer.unit_price)],
          ["Quantity", num(offer.qty)],
          ["Tax", `${inr(offer.tax)}${offer.tax_rate != null ? ` (${(offer.tax_rate * 100).toFixed(0)}%)` : ""}`],
          ["Shipping", inr(offer.shipping)],
          ["Landed cost", inr(offer.total_landed_cost)],
          ["Lead time", offer.lead_time_days != null ? `${offer.lead_time_days} days` : "Not specified"],
          ["Valid until", dateTime(offer.valid_until)],
          ["Recorded", dateTime(offer.created_at)],
        ]} />
        {offer.status === "accepted" && <p className="note">Agreed terms on this line. This is a negotiated agreement, not a placed order.</p>}
        {offer.status === "flagged" && <p className="note note-warn">Outside the author's authority. It does not count until its author confirms it with a reason.</p>}
      </section>

      <section className="ev-section">
        <h3>Validation</h3>
        {turn ? (
          <>
            <div className="badges"><GuardBadge status={g?.status} /></div>
            {g?.reasons && g.reasons.length > 0 && <ul className="reasons">{g.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
            {g?.override_reason && <p className="note">Override reason: “{g.override_reason}” — confirmed by {g.confirmed_by}</p>}
            {(!g?.reasons || g.reasons.length === 0) && g?.status === "ok" && <p className="muted">Passed every authority check for its side.</p>}
          </>
        ) : <p className="muted">The related turn is not visible to your role.</p>}
      </section>

      {turn && (
        <section className="ev-section">
          <h3>Negotiation turn</h3>
          <KV items={[
            ["Turn id", <span className="mono">{turn.id}</span>],
            ["Round", String(turn.round)],
            ["Controller", turn.controller === "human" ? "Human" : turn.controller === "engine" ? "System" : "Agent"],
            ["Action", turn.validated_action?.type ?? "—"],
            ["Message", turn.message || "—"],
            ["Model attempts", String(turn.attempts)],
          ]} />
          {turn.notes.length > 0 && (
            <details className="tech">
              <summary>Technical trace</summary>
              <ul>{turn.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
              {turn.raw_llm_output && <pre>{turn.raw_llm_output}</pre>}
            </details>
          )}
        </section>
      )}

      {call && (
        <section className="ev-section">
          <h3>Voice call</h3>
          <KV items={[
            ["Call", call.mode === "recorded" ? "Recorded call (demo replay)" : "Live call"],
            ["Status", call.status],
            ["Read-back confirmed", call.terms?.readback_confirmed ? "Yes" : "No"],
            ["Conversation id", call.conversation_id ?? "—"],
          ]} />
        </section>
      )}

      <section className="ev-section">
        <h3>Revision history on this line</h3>
        <ol className="history">
          {history.map((o) => (
            <li key={o.id} className={o.id === offer.id ? "history-on" : ""}>
              <span className="mono">R{o.round} v{o.version}</span>
              <span>{o.side === "seller" ? "Supplier ask" : "Buyer bid"}</span>
              <strong>{inr(o.unit_price)}</strong>
              <span className="muted">{sourceLabel(o.source, o.voice_mode)} · {STATUS_LABEL[o.status]}</span>
            </li>
          ))}
        </ol>
      </section>
    </Drawer>
  );
}
