import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth, useCompanies } from "../auth";
import { EvidenceDrawer, OfferTable } from "../components/Offers";
import { FlaggedList, HumanOfferPanel } from "../components/Forms";
import { PriceChart } from "../components/PriceChart";
import { RecommendationView } from "../components/RecommendationView";
import { Timeline } from "../components/Timeline";
import { VoicePanel } from "../components/VoicePanel";
import {
  Badge, Card, ControllerBadge, Empty, ErrorState, Icon, Loading, Tabs, useAction,
} from "../components/ui";
import { current, flagged, maxRounds, supplierRows } from "../derive";
import { dateTime, inr, num } from "../format";
import { useRfqLive } from "../hooks";
import type { Offer, Rfq, SellerProduct, Turn } from "../types";

type TabId = "offers" | "negotiation" | "recommendation" | "voice";

export function RfqStatusBadge({ status }: { status: Rfq["status"] }) {
  const map: Record<string, [string, "neutral" | "info" | "ok"]> = {
    draft: ["Draft", "neutral"], negotiating: ["In negotiation", "info"], completed: ["Completed", "ok"],
  };
  const [label, tone] = map[status] ?? [status, "neutral"];
  return <Badge tone={tone}>{label}</Badge>;
}

// ------------------------------------------------------------------ stepper
type StepState = "done" | "current" | "todo";

function Stepper({ steps }: { steps: { label: string; state: StepState; detail?: string }[] }) {
  return (
    <ol className="stepper" aria-label="Negotiation progress">
      {steps.map((s, i) => (
        <li key={s.label} className={`step step-${s.state}`} aria-current={s.state === "current" ? "step" : undefined}>
          <span className="step-dot" aria-hidden="true">{s.state === "done" ? "✓" : i + 1}</span>
          <span className="step-text">
            <span className="step-label">{s.label}</span>
            {s.detail && <span className="step-detail">{s.detail}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

function progressSteps(rfq: Rfq, turns: Turn[], hasRec: boolean, role: "buyer" | "seller") {
  const sellers = rfq.participants.filter((p) => p.side === "seller").length;
  const priced = turns.filter((t) => t.guardrail_result?.status);
  const count = (s: string) => priced.filter((t) => t.guardrail_result.status === s).length;
  const neg: StepState = rfq.status === "draft" ? "todo" : rfq.status === "negotiating" ? "current" : "done";
  return [
    { label: "RFQ created", state: "done" as StepState, detail: dateTime(rfq.created_at) },
    { label: "Suppliers invited", state: (sellers ? "done" : "todo") as StepState,
      detail: role === "buyer" ? `${sellers} supplier${sellers === 1 ? "" : "s"}` : undefined },
    { label: "Negotiation running", state: neg,
      detail: rfq.status === "draft" ? "not started" : `round ${rfq.round} of ${maxRounds(rfq)}` },
    { label: "Offers validated", state: (priced.length ? (rfq.status === "completed" ? "done" : "current") : "todo") as StepState,
      detail: priced.length ? `${count("ok")} passed · ${count("blocked")} blocked · ${count("flagged_outside_authority")} flagged` : undefined },
    role === "buyer"
      ? { label: "Recommendation ready", state: (hasRec ? "done" : rfq.status === "completed" ? "current" : "todo") as StepState }
      : { label: "Negotiation closed", state: (rfq.status === "completed" ? "done" : "todo") as StepState },
  ];
}

// ------------------------------------------------------------------ workspace
export function RfqWorkspace({ id, switcher }: { id: string; switcher?: ReactNode }) {
  const { session } = useAuth();
  const role = session!.role;
  const me = session!.company_id;
  const { name, byId } = useCompanies();
  const live = useRfqLive(id, role === "buyer");
  const { rfq, offers, turns, calls, rec } = live;
  const [tab, setTab] = useState<TabId>("offers");
  const [evidence, setEvidence] = useState<Offer | null>(null);
  const [mpn, setMpn] = useState<string>("");
  const [engineOnly, setEngineOnly] = useState(true);
  const [products, setProducts] = useState<SellerProduct[]>([]);
  const { busy, run } = useAction();

  useEffect(() => {
    if (role === "seller") api.sellerProducts().then(setProducts).catch(() => undefined);
  }, [role]);
  useEffect(() => {
    if (rfq && !rfq.lines.some((l) => l.mpn === mpn)) setMpn(rfq.lines[0]?.mpn ?? "");
  }, [rfq, mpn]);
  useEffect(() => {
    if (rec && tab === "offers" && rfq?.status === "completed") setTab("recommendation");
    // only when a recommendation first appears
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rec?.id]);

  const rows = useMemo(() => (rfq ? supplierRows(rfq, offers) : []), [rfq, offers]);

  if (live.loading && !rfq) return <Loading label="Loading request" />;
  if (live.error || !rfq) return <ErrorState message={live.error ?? "Request not found"} onRetry={() => live.refresh()} />;

  const sellers = rfq.participants.filter((p) => p.side === "seller").map((p) => p.company_id);
  const mySide = rfq.participants.find((p) => p.company_id === me);
  const human = mySide?.controller === "human";
  const negotiating = rfq.status === "negotiating";
  const totalQty = rfq.lines.reduce((a, l) => a + l.qty, 0);
  const pendingMine = flagged(offers).filter((o) => o.created_by === `${role}:${me}`).length;
  const refresh = () => live.refresh().catch(() => undefined);

  const openSupplierEvidence = (companyId: string) => {
    const first = rfq.lines.map((l) => current(offers, companyId, l.mpn)).find(Boolean);
    if (first) setEvidence(first);
  };

  const hint = (part: string): string | null => {
    if (role === "buyer") {
      const lim = rfq.buyer_limits?.[part];
      return lim ? `Your ceiling ${inr(lim.ceiling)} · target ${inr(lim.target)} (visible only to you)` : null;
    }
    const p = products.find((x) => x.mpn === part);
    return p?.pricing.floor_price != null ? `Your floor ${inr(p.pricing.floor_price)} (visible only to you)` : null;
  };

  const tabs: { id: TabId; label: string; count?: number }[] = [
    { id: "offers", label: role === "buyer" ? "Offer comparison" : "Your offers" },
    { id: "negotiation", label: "Negotiation log", count: turns.length },
    ...(role === "buyer" ? [{ id: "recommendation" as TabId, label: "Recommendation" }] : []),
    { id: "voice", label: "Voice", count: calls.length },
  ];

  return (
    <div className="workspace">
      <div className="ws-head">
        <div>
          <div className="crumbs">
            <Link to={role === "buyer" ? "/buyer/requests" : "/seller"}>{role === "buyer" ? "Requests" : "Inbox"}</Link>
            <span>/</span><span className="mono">{rfq.id}</span>
          </div>
          <h1 className="ws-title">{rfq.title} <RfqStatusBadge status={rfq.status} /></h1>
          <p className="muted">
            {role === "seller" ? <>Buyer: {name(rfq.buyer_company_id)} · </> : null}
            {rfq.engine_only ? "Deterministic engine run" : rfq.status !== "draft" ? "AI agents with guardrails" : "Not started"}
          </p>
        </div>
        <div className="ws-actions">
          {switcher}
          {role === "buyer" && rfq.status === "draft" && (
            <>
              <label className="check" title="Deterministic: same result every run. Untick to let the AI agent choose moves.">
                <input type="checkbox" checked={engineOnly} onChange={(e) => setEngineOnly(e.target.checked)} />
                Deterministic engine
              </label>
              <button className="btn btn-ghost" disabled={busy !== null}
                onClick={() => run("start", () => api.start(rfq.id, { engine_only: engineOnly }), "Negotiation started").then(refresh)}>
                {busy === "start" ? "Starting…" : "Start round 0"}
              </button>
              <button className="btn btn-primary" disabled={busy !== null}
                onClick={() => run("all", () => api.start(rfq.id, { run_all: true, engine_only: engineOnly }), "Negotiation complete").then(refresh)}>
                <Icon name="play" size={14} /> {busy === "all" ? (engineOnly ? "Running…" : "AI agents negotiating… up to 2 min") : "Run full negotiation"}
              </button>
            </>
          )}
          {role === "buyer" && negotiating && (
            <button className="btn btn-primary" disabled={busy !== null}
              onClick={() => run("round", () => api.nextRound(rfq.id)).then(refresh)}>
              <Icon name="next" size={14} /> {busy === "round" ? "Playing round…" : rfq.round + 1 >= maxRounds(rfq) ? "Play final round" : `Play round ${rfq.round + 1}`}
            </button>
          )}
          {role === "buyer" && rfq.status === "completed" && tab !== "recommendation" && (
            <button className="btn btn-primary" onClick={() => setTab("recommendation")}>View recommendation</button>
          )}
        </div>
      </div>

      <div className="banner">
        <div className="tiles">
          <Tile label="BOM lines" value={String(rfq.lines.length)} sub={`${num(totalQty)} units in total`} />
          {role === "buyer" && <Tile label="Budget" value={inr(rfq.budget, true)} sub={rfq.budget_basis === "pre_tax" ? "before tax" : "landed, incl. tax"} />}
          <Tile label="Deadline" value={`${rfq.deadline_days} days`} sub={`by ${new Date(rfq.deadline).toLocaleDateString()}`} />
          {role === "buyer" && <Tile label="Suppliers" value={String(sellers.length)} sub={`${rows.filter((r) => r.quotedLines).length} quoting`} />}
          <Tile label="Round" value={rfq.status === "draft" ? "—" : `${rfq.round} / ${maxRounds(rfq)}`} sub={rfq.status === "draft" ? "not started" : rfq.status === "completed" ? "final" : "in progress"} />
        </div>
      </div>

      <Stepper steps={progressSteps(rfq, turns, !!rec, role)} />

      <div className="ws-grid">
        <div className="ws-main">
          <Tabs tabs={tabs} value={tab} onChange={setTab} />
          {tab === "offers" && (
            <div className="stack">
              <Card title={role === "buyer" ? "Supplier offers" : "Your thread"}
                subtitle={role === "buyer" ? "Current standing offer per supplier. Click a row for line detail and evidence." : "Your latest asks and the buyer's bids, line by line."}>
                {rfq.status === "draft" && !offers.length
                  ? <Empty title="No offers yet">{role === "buyer" ? "Start the negotiation to collect opening quotes." : "The buyer has not started this negotiation."}</Empty>
                  : <OfferTable rows={rows} name={name} reliability={(sid) => byId[sid]?.reliability_score}
                      ranked={rec?.ranked ?? null} rejected={rec?.rejected ?? null} onEvidence={setEvidence} showFilters={role === "buyer"} />}
              </Card>
              <Card title="Price by round"
                subtitle="Supplier asks per round from recorded offers only"
                actions={rfq.lines.length > 1 && (
                  <div className="seg" role="group" aria-label="Part">
                    {rfq.lines.map((l) => (
                      <button key={l.mpn} className={`seg-btn ${mpn === l.mpn ? "seg-on" : ""}`} onClick={() => setMpn(l.mpn)}>{l.mpn}</button>
                    ))}
                  </div>
                )}>
                <PriceChart offers={offers} mpn={mpn} suppliers={sellers} name={name} maxRound={maxRounds(rfq)} showBids />
              </Card>
            </div>
          )}
          {tab === "negotiation" && (
            <Card title="Negotiation log" subtitle="Every move, who made it, and what the guardrail decided">
              <Timeline turns={turns} offers={offers} name={name} suppliers={role === "buyer" ? sellers : []} onEvidence={setEvidence} />
            </Card>
          )}
          {tab === "recommendation" && role === "buyer" && (
            <RecommendationView rec={rec} status={rfq.status} onSupplier={openSupplierEvidence} />
          )}
          {tab === "voice" && (
            <VoicePanel rfq={rfq} calls={calls} offers={offers} name={name} canAct={role === "buyer"} onChanged={refresh} />
          )}
        </div>

        <aside className="ws-side">
          <Card title="Your side" subtitle={role === "buyer" ? "Buyer controls" : "Supplier controls"}>
            <div className="control-row">
              <span>Controlled by</span>
              {mySide ? <ControllerBadge controller={mySide.controller} /> : <span className="muted">—</span>}
            </div>
            {negotiating ? (
              <button className={`btn ${human ? "btn-ghost" : "btn-dark"} btn-block`} disabled={busy !== null}
                onClick={() => run("hand", () => api.handover(rfq.id, human ? "agent" : "human"),
                  human ? "Handed back to the agent" : "You are now in control").then(refresh)}>
                <Icon name={human ? "bot" : "hand"} size={14} /> {human ? "Hand back to agent" : "Take over negotiation"}
              </button>
            ) : <p className="muted">{rfq.status === "draft" ? "Available once the negotiation starts." : "Negotiation has ended."}</p>}
            <p className="cell-sub">While you are in control your agent stops moving. Offers outside your authority are recorded but flagged until you confirm them.</p>
          </Card>

          {negotiating && human && (
            <Card title="Make a move">
              <HumanOfferPanel rfq={rfq} offers={offers} side={role} myCompany={me} name={name} hint={hint} onDone={refresh} />
            </Card>
          )}

          <Card title="Awaiting your confirmation" subtitle={pendingMine ? `${pendingMine} offer${pendingMine === 1 ? "" : "s"} outside authority` : undefined}>
            <FlaggedList rfq={rfq} offers={offers} mine={`${role}:${me}`} name={name} onDone={refresh} />
          </Card>

          <Card title="Requirements">
            <ul className="req-list">
              {rfq.lines.map((l) => (
                <li key={l.mpn}>
                  <span className="mono">{l.mpn}</span>
                  <span className="num">{num(l.qty)} pcs</span>
                  {Object.entries(l.required_specs).map(([k, r]) => (
                    <span key={k} className="cell-sub">{k} {r.op} {Array.isArray(r.value) ? r.value.join(", ") : String(r.value)}</span>
                  ))}
                </li>
              ))}
            </ul>
          </Card>
        </aside>
      </div>

      {evidence && (
        <EvidenceDrawer offer={evidence} offers={offers} turns={turns} calls={calls} name={name} onClose={() => setEvidence(null)} />
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}</span>
      {sub && <span className="tile-sub">{sub}</span>}
    </div>
  );
}
