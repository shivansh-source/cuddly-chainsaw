import { useEffect, useState, type FormEvent } from "react";
import { api, type ProductInput } from "../api";
import { flagged, latest } from "../derive";
import { inr } from "../format";
import type { Company, HumanTurnResult, Offer, Rfq, RfqLine, SellerProduct, SpecRule } from "../types";
import { Badge, Drawer, GuardBadge, Icon, StatusBadge, useAction } from "./ui";

// ---------------------------------------------------------------- create RFQ
interface LineDraft { mpn: string; qty: string; specKey: string; specOp: SpecRule["op"]; specValue: string }
const blankLine = (): LineDraft => ({ mpn: "", qty: "", specKey: "", specOp: ">=", specValue: "" });
const SAMPLE: LineDraft[] = [
  { mpn: "ESP32-WROOM-32E", qty: "100", specKey: "flash_mb", specOp: ">=", specValue: "4" },
  { mpn: "BME280", qty: "100", specKey: "", specOp: ">=", specValue: "" },
  { mpn: "USB4105-GF-A", qty: "200", specKey: "", specOp: ">=", specValue: "" },
];

function parseSpecValue(op: SpecRule["op"], raw: string): unknown {
  const asValue = (s: string) => (s.trim() !== "" && !Number.isNaN(Number(s)) ? Number(s) : s.trim());
  return op === "in" ? raw.split(",").map(asValue) : asValue(raw);
}

export function CreateRfqDrawer({ suppliers, onClose, onCreated }: {
  suppliers: Company[]; onClose: () => void; onCreated: (rfq: Rfq) => void;
}) {
  const [title, setTitle] = useState("");
  const [budget, setBudget] = useState("");
  const [deadline, setDeadline] = useState("14");
  const [rounds, setRounds] = useState("3");
  const [lines, setLines] = useState<LineDraft[]>([blankLine()]);
  const [invite, setInvite] = useState<string[]>([]);
  const [mpns, setMpns] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const { busy, run } = useAction();

  useEffect(() => {
    Promise.all(suppliers.map((s) => api.catalog(s.id).catch(() => [])))
      .then((all) => setMpns(Array.from(new Set(all.flat().map((i) => i.mpn))).sort()));
  }, [suppliers]);

  const setLine = (i: number, patch: Partial<LineDraft>) =>
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const parsed: RfqLine[] = [];
    for (const [i, l] of lines.entries()) {
      const qty = Number(l.qty);
      if (!l.mpn.trim()) return setError(`Line ${i + 1}: enter an exact part number (MPN).`);
      if (!Number.isInteger(qty) || qty < 1) return setError(`Line ${i + 1}: quantity must be a whole number of at least 1.`);
      const required_specs: Record<string, SpecRule> = {};
      if (l.specKey.trim()) {
        if (!l.specValue.trim()) return setError(`Line ${i + 1}: give a value for ${l.specKey}.`);
        required_specs[l.specKey.trim()] = { op: l.specOp, value: parseSpecValue(l.specOp, l.specValue) };
      }
      parsed.push({ mpn: l.mpn.trim(), qty, mandatory: true, required_specs });
    }
    if (!title.trim()) return setError("Give the request a title.");
    if (!(Number(budget) > 0)) return setError("Budget must be a positive amount.");
    if (!invite.length) return setError("Invite at least one supplier.");
    const created = await run("create", () => api.createRfq({
      title: title.trim(), budget: Number(budget), budget_basis: "landed_incl_tax", currency: "INR",
      deadline_days: Number(deadline), max_rounds: Number(rounds), lines: parsed, invite,
    }), "Request created");
    if (created) onCreated(created);
  };

  return (
    <Drawer title="New request for quotation" subtitle="Exact part numbers only. Mandatory specs are checked against each supplier's catalog." onClose={onClose} wide>
      <form onSubmit={submit} className="form" noValidate>
        <div className="form-grid">
          <label className="field span-2">Title
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Sensor node batch" required />
          </label>
          <label className="field">Budget (INR, incl. tax)
            <input value={budget} onChange={(e) => setBudget(e.target.value)} inputMode="decimal" placeholder="93000" />
          </label>
          <label className="field">Delivery deadline (days)
            <input value={deadline} onChange={(e) => setDeadline(e.target.value)} type="number" min={1} />
          </label>
          <label className="field">Negotiation rounds
            <select value={rounds} onChange={(e) => setRounds(e.target.value)}>
              {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>

        <div className="form-section-head">
          <h3>Bill of materials</h3>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setLines(SAMPLE.map((l) => ({ ...l })))}>
            Use sample BOM (ESP32 · BME280 · USB-C)
          </button>
        </div>
        <datalist id="mpns">{mpns.map((m) => <option key={m} value={m} />)}</datalist>
        <div className="bom">
          <div className="bom-head"><span>MPN</span><span>Qty</span><span>Mandatory spec (optional)</span><span /></div>
          {lines.map((l, i) => (
            <div key={i} className="bom-row">
              <input aria-label={`Line ${i + 1} MPN`} list="mpns" value={l.mpn} onChange={(e) => setLine(i, { mpn: e.target.value })} placeholder="e.g. BME280" />
              <input aria-label={`Line ${i + 1} quantity`} value={l.qty} onChange={(e) => setLine(i, { qty: e.target.value })} inputMode="numeric" placeholder="100" />
              <div className="spec">
                <input aria-label={`Line ${i + 1} spec key`} value={l.specKey} onChange={(e) => setLine(i, { specKey: e.target.value })} placeholder="flash_mb" />
                <select aria-label={`Line ${i + 1} comparison`} value={l.specOp} onChange={(e) => setLine(i, { specOp: e.target.value as SpecRule["op"] })}>
                  {[">=", "<=", "==", "in"].map((o) => <option key={o}>{o}</option>)}
                </select>
                <input aria-label={`Line ${i + 1} spec value`} value={l.specValue} onChange={(e) => setLine(i, { specValue: e.target.value })} placeholder={l.specOp === "in" ? "a, b" : "8"} />
              </div>
              <button type="button" className="icon-btn" aria-label={`Remove line ${i + 1}`} disabled={lines.length === 1}
                onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}><Icon name="close" size={14} /></button>
            </div>
          ))}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setLines((ls) => [...ls, blankLine()])}>
            <Icon name="plus" size={14} /> Add line
          </button>
        </div>

        <h3>Invite suppliers</h3>
        <div className="invite">
          {suppliers.map((s) => (
            <label key={s.id} className={`invite-item ${invite.includes(s.id) ? "on" : ""}`}>
              <input type="checkbox" checked={invite.includes(s.id)}
                onChange={(e) => setInvite((v) => (e.target.checked ? [...v, s.id] : v.filter((x) => x !== s.id)))} />
              <span>
                <strong>{s.name}</strong>
                <span className="cell-sub">{s.location} · reliability {s.reliability_score ?? "—"}{s.verified === false ? " · unverified" : ""}</span>
              </span>
            </label>
          ))}
        </div>

        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy !== null}>{busy ? "Creating…" : "Create request"}</button>
        </div>
      </form>
    </Drawer>
  );
}

// ---------------------------------------------------------------- human move
export function HumanOfferPanel({ rfq, offers, side, myCompany, name, hint, onDone }: {
  rfq: Rfq; offers: Offer[]; side: "buyer" | "seller"; myCompany: string; name: (id: string) => string;
  hint: (mpn: string) => string | null; onDone: () => void;
}) {
  const sellers = rfq.participants.filter((p) => p.side === "seller").map((p) => p.company_id);
  const [sellerId, setSellerId] = useState(side === "seller" ? myCompany : sellers[0] ?? "");
  const [mpn, setMpn] = useState(rfq.lines[0]?.mpn ?? "");
  const [type, setType] = useState<"counter" | "accept" | "walk_away">("counter");
  const [price, setPrice] = useState("");
  const [qty, setQty] = useState("");
  const [lead, setLead] = useState("");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<HumanTurnResult | null>(null);
  const { busy, run } = useAction();

  const thread = side === "seller" ? myCompany : sellerId;
  const theirs = latest(offers, thread, mpn, side === "seller" ? "buyer" : "seller");
  const mine = latest(offers, thread, mpn, side);
  const line = rfq.lines.find((l) => l.mpn === mpn);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const out = await run("turn", () => api.humanTurn(rfq.id, {
      mpn, type,
      unit_price: type === "counter" ? Number(price) : undefined,
      qty: qty ? Number(qty) : undefined,
      lead_time_days: lead ? Number(lead) : undefined,
      message: message || undefined,
      seller_id: side === "buyer" ? sellerId : undefined,
    }));
    if (out) {
      setResult(out);
      setPrice("");
      setMessage("");
      onDone();
    }
  };

  return (
    <form className="form" onSubmit={submit}>
      <div className="form-grid">
        {side === "buyer" && (
          <label className="field">Supplier
            <select value={sellerId} onChange={(e) => setSellerId(e.target.value)}>
              {sellers.map((s) => <option key={s} value={s}>{name(s)}</option>)}
            </select>
          </label>
        )}
        <label className="field">Part
          <select value={mpn} onChange={(e) => setMpn(e.target.value)}>
            {rfq.lines.map((l) => <option key={l.mpn} value={l.mpn}>{l.mpn} · {l.qty} pcs</option>)}
          </select>
        </label>
        <label className="field">Move
          <select value={type} onChange={(e) => setType(e.target.value as typeof type)}>
            <option value="counter">Make an offer</option>
            <option value="accept" disabled={!theirs}>Accept their current offer</option>
            <option value="walk_away">Walk away from this line</option>
          </select>
        </label>
        {type === "counter" && (
          <label className="field">Unit price (INR)
            <input value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal" required placeholder={theirs ? String(theirs.unit_price) : ""} />
          </label>
        )}
        {type === "counter" && (
          <label className="field">Quantity
            <input value={qty} onChange={(e) => setQty(e.target.value)} inputMode="numeric" placeholder={String(line?.qty ?? "")} />
          </label>
        )}
        {type === "counter" && side === "seller" && (
          <label className="field">Lead time (days)
            <input value={lead} onChange={(e) => setLead(e.target.value)} inputMode="numeric" placeholder="catalog" />
          </label>
        )}
        <label className="field span-2">Message (optional)
          <input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Shown to the other side" />
        </label>
      </div>
      <div className="context-row">
        <span>Their current: <strong>{theirs ? inr(theirs.unit_price) : "none"}</strong></span>
        <span>Yours: <strong>{mine ? inr(mine.unit_price) : "none"}</strong></span>
        {hint(mpn) && <span className="muted">{hint(mpn)}</span>}
      </div>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={busy !== null || (type === "counter" && !(Number(price) > 0))}>
          {busy ? "Sending…" : "Send move"}
        </button>
      </div>
      {result && (
        <div className="result">
          <div className="badges"><GuardBadge status={result.guardrail.status} />{result.offer && <StatusBadge status={result.offer.status} />}</div>
          {result.guardrail.reasons && result.guardrail.reasons.length > 0 && (
            <ul className="reasons">{result.guardrail.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          )}
          {result.guardrail.status === "flagged_outside_authority" && (
            <p className="note note-warn">Recorded but outside your authority. It will not count until you confirm it with a reason below.</p>
          )}
          {result.reply && (
            <p>Agent replied: <strong>{result.reply.status === "accepted" ? "accepted at " : ""}{inr(result.reply.unit_price)}</strong> <Badge>{result.reply.source === "engine" ? "Engine" : "AI agent"}</Badge></p>
          )}
        </div>
      )}
    </form>
  );
}

export function FlaggedList({ rfq, offers, mine, name, onDone }: {
  rfq: Rfq; offers: Offer[]; mine: string; name: (id: string) => string; onDone: () => void;
}) {
  const items = flagged(offers).filter((o) => o.created_by === mine);
  const [reason, setReason] = useState<Record<string, string>>({});
  const { busy, run } = useAction();
  if (!items.length) return <p className="muted">Nothing awaiting confirmation.</p>;
  return (
    <ul className="flagged">
      {items.map((o) => (
        <li key={o.id}>
          <div className="rej-head">
            <span className="mono">{o.mpn}</span>
            <strong>{inr(o.unit_price)}</strong>
            <span className="muted">× {o.qty} · {name(o.company_id)} · round {o.round}</span>
            <StatusBadge status={o.status} />
          </div>
          <form className="confirm-row" onSubmit={async (e) => {
            e.preventDefault();
            const ok = await run(o.id, () => api.confirm(rfq.id, o.id, reason[o.id] ?? ""), "Override confirmed and logged");
            if (ok) onDone();
          }}>
            <input aria-label="Reason for confirming" placeholder="Reason (required, logged)" value={reason[o.id] ?? ""}
              onChange={(e) => setReason((r) => ({ ...r, [o.id]: e.target.value }))} />
            <button className="btn btn-ghost btn-sm" disabled={busy !== null || !(reason[o.id] ?? "").trim()}>Confirm</button>
          </form>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- seller product
export function ProductDrawer({ initial, onClose, onSaved }: {
  initial?: SellerProduct; onClose: () => void; onSaved: () => void;
}) {
  const [f, setF] = useState({
    mpn: initial?.mpn ?? "", description: initial?.description ?? "",
    specs: initial ? JSON.stringify(initial.specs) : "{}",
    stock_qty: String(initial?.stock_qty ?? ""), lead_time_days: String(initial?.lead_time_days ?? ""),
    moq: String(initial?.moq ?? "1"), tax_rate: String(initial?.tax_rate ?? 0.18),
    list_price: String(initial?.pricing.list_price ?? ""), floor_price: String(initial?.pricing.floor_price ?? ""),
    tiers: JSON.stringify(initial?.pricing.tiers ?? [{ min_qty: 100, discount_pct: 0.05 }]),
    concession_step_pct: String(initial?.pricing.concession_step_pct ?? 0.25),
    max_rounds: String(initial?.pricing.max_rounds ?? 3),
  });
  const [error, setError] = useState<string | null>(null);
  const { busy, run } = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    let specs: Record<string, unknown>, tiers: ProductInput["tiers"];
    try {
      specs = JSON.parse(f.specs || "{}");
      tiers = JSON.parse(f.tiers || "[]");
    } catch {
      return setError("Specs and tiers must be valid JSON.");
    }
    if (Number(f.floor_price) > Number(f.list_price)) return setError("Floor price cannot be above the list price.");
    const ok = await run("save", () => api.upsertProduct({
      mpn: f.mpn.trim(), description: f.description, specs, tiers,
      stock_qty: Number(f.stock_qty), lead_time_days: Number(f.lead_time_days), moq: Number(f.moq),
      tax_rate: Number(f.tax_rate), list_price: Number(f.list_price), floor_price: Number(f.floor_price),
      concession_step_pct: Number(f.concession_step_pct), max_rounds: Number(f.max_rounds),
    }), "Product saved");
    if (ok) onSaved();
  };

  return (
    <Drawer title={initial ? `Edit ${initial.mpn}` : "Add product"} subtitle="Saves the catalog item and its pricing rule together. Only you can see your floor." onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field">MPN<input value={f.mpn} onChange={set("mpn")} required disabled={!!initial} /></label>
          <label className="field">Description<input value={f.description} onChange={set("description")} /></label>
          <label className="field">Stock<input value={f.stock_qty} onChange={set("stock_qty")} inputMode="numeric" required /></label>
          <label className="field">Lead time (days)<input value={f.lead_time_days} onChange={set("lead_time_days")} inputMode="numeric" required /></label>
          <label className="field">MOQ<input value={f.moq} onChange={set("moq")} inputMode="numeric" required /></label>
          <label className="field">Tax rate (0–1)<input value={f.tax_rate} onChange={set("tax_rate")} inputMode="decimal" /></label>
          <label className="field">List price (INR)<input value={f.list_price} onChange={set("list_price")} inputMode="decimal" required /></label>
          <label className="field">Floor price (INR)<input value={f.floor_price} onChange={set("floor_price")} inputMode="decimal" required /></label>
          <label className="field">Concession per round (0–1)<input value={f.concession_step_pct} onChange={set("concession_step_pct")} inputMode="decimal" /></label>
          <label className="field">Max rounds<input value={f.max_rounds} onChange={set("max_rounds")} inputMode="numeric" /></label>
          <label className="field span-2">Specs (JSON, unit in key)<input className="mono" value={f.specs} onChange={set("specs")} placeholder='{"flash_mb": 8}' /></label>
          <label className="field span-2">Quantity tiers (JSON)<input className="mono" value={f.tiers} onChange={set("tiers")} /></label>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy !== null}>{busy ? "Saving…" : "Save product"}</button>
        </div>
      </form>
    </Drawer>
  );
}
