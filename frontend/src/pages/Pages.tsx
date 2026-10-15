import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth, useCompanies } from "../auth";
import { CreateRfqDrawer, ProductDrawer } from "../components/Forms";
import { Timeline } from "../components/Timeline";
import { Badge, Card, Empty, ErrorState, Icon, Loading } from "../components/ui";
import { greeting, inr, longDate, num } from "../format";
import { useAsync } from "../hooks";
import type { CatalogItem, Rfq, SellerProduct, Turn } from "../types";
import { RfqStatusBadge, RfqWorkspace } from "./Workspace";

// ------------------------------------------------------------------ login
const DEMO = [
  { label: "Buyer · Acme Robotics", email: "buyer@acme.test" },
  { label: "Supplier · Volt Components", email: "sales@volt.test" },
  { label: "Supplier · Circuit Bazaar", email: "sales@circuitbazaar.test" },
];

const SAMPLE_RFQ = "/buyer/rfq/rfq_demo_1";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const params = new URLSearchParams(window.location.search);
  const sample = params.has("sample");
  // Only same-app paths are honoured as a post-login destination.
  const nextParam = params.get("next");
  const next = sample ? SAMPLE_RFQ : nextParam && nextParam.startsWith("/") && !nextParam.startsWith("//") ? nextParam : null;
  const [email, setEmail] = useState(sample ? "buyer@acme.test" : "");
  const [password, setPassword] = useState(sample ? "demo1234" : "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const s = await login(email, password);
      const home = s.role === "buyer" ? "/buyer" : "/seller";
      navigate(next && next.startsWith(home) ? next : home, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="login-card">
        <Link to="/" className="brand brand-lg"><span className="brand-mark" aria-hidden="true">N</span> The Negotiator</Link>
        <p className="muted">AI procurement operations: agents negotiate within enforced limits, every offer is validated and traceable.</p>
        {sample && <p className="note">Sample workspace: the demo buyer account is filled in. Sign in to open the seeded request.</p>}
        <form className="form" onSubmit={submit}>
          <label className="field">Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></label>
          <label className="field">Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="btn btn-primary btn-block" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
        <div className="demo-accounts">
          <span className="muted">Demo accounts (password demo1234)</span>
          {DEMO.map((d) => (
            <button key={d.email} type="button" className="chip" onClick={() => { setEmail(d.email); setPassword("demo1234"); }}>
              {d.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ shared bits
function Greeting({ title, sub, stats }: { title: string; sub: string; stats: { label: string; value: string; hint?: string }[] }) {
  return (
    <div className="hello">
      <div className="hello-text">
        <span className="muted">{longDate()}</span>
        <h1>{title}</h1>
        <p className="muted">{sub}</p>
      </div>
      <div className="tiles">
        {stats.map((s) => (
          <div key={s.label} className="tile">
            <span className="tile-label">{s.label}</span>
            <span className="tile-value">{s.value}</span>
            {s.hint && <span className="tile-sub">{s.hint}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function RfqTable({ rfqs, to, role, name }: { rfqs: Rfq[]; to: (r: Rfq) => string; role: "buyer" | "seller"; name: (id: string) => string }) {
  const navigate = useNavigate();
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr>
          <th>Request</th>{role === "seller" && <th>Buyer</th>}<th>Parts</th><th className="num">Units</th>
          {role === "buyer" && <th className="num">Budget</th>}<th className="num">Deadline</th>
          {role === "buyer" && <th className="num">Suppliers</th>}<th className="num">Round</th><th>Status</th>
        </tr></thead>
        <tbody>
          {rfqs.map((r) => (
            <tr key={r.id} className="clickable" onClick={() => navigate(to(r))}>
              <td><Link to={to(r)} className="cell-main" onClick={(e) => e.stopPropagation()}>{r.title}</Link><div className="cell-sub mono">{r.id}</div></td>
              {role === "seller" && <td>{name(r.buyer_company_id)}</td>}
              <td className="mono small">{r.lines.map((l) => l.mpn).join(", ")}</td>
              <td className="num">{num(r.lines.reduce((a, l) => a + l.qty, 0))}</td>
              {role === "buyer" && <td className="num">{inr(r.budget, true)}</td>}
              <td className="num">{r.deadline_days} d</td>
              {role === "buyer" && <td className="num">{r.participants.filter((p) => p.side === "seller").length}</td>}
              <td className="num">{r.status === "draft" ? "—" : `${r.round}/${r.max_rounds ?? 3}`}</td>
              <td><RfqStatusBadge status={r.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ buyer
export function BuyerOverview() {
  const { session } = useAuth();
  const rfqs = useAsync(() => api.rfqs(), []);
  const [focus, setFocus] = useState<string>("");
  const list = rfqs.data ?? [];

  useEffect(() => {
    if (!list.length || list.some((r) => r.id === focus)) return;
    const pick = list.find((r) => r.status === "negotiating") ?? list.find((r) => r.status === "draft") ?? list[0];
    setFocus(pick.id);
  }, [list, focus]);

  if (rfqs.loading && !rfqs.data) return <Loading label="Loading your requests" />;
  if (rfqs.error) return <ErrorState message={rfqs.error} onRetry={rfqs.reload} />;
  const count = (s: string) => list.filter((r) => r.status === s).length;

  return (
    <div className="page">
      <Greeting title={`${greeting()}, ${session?.company_name ?? "buyer"}`}
        sub="Your agents negotiate within your limits. Every offer is validated and traceable."
        stats={[
          { label: "Requests", value: String(list.length) },
          { label: "In negotiation", value: String(count("negotiating")) },
          { label: "Completed", value: String(count("completed")), hint: "recommendation available" },
          { label: "Draft", value: String(count("draft")), hint: "ready to start" },
        ]} />
      {list.length === 0 ? (
        <Empty title="No requests yet" action={<Link className="btn btn-primary" to="/buyer/requests?new=1">Create a request</Link>}>
          Create a request to start comparing supplier offers.
        </Empty>
      ) : focus ? (
        <RfqWorkspace id={focus} switcher={
          <label className="select-label">Request
            <select value={focus} onChange={(e) => setFocus(e.target.value)}>
              {list.map((r) => <option key={r.id} value={r.id}>{r.title} · {r.status}</option>)}
            </select>
          </label>
        } />
      ) : null}
    </div>
  );
}

export function BuyerRequests() {
  const rfqs = useAsync(() => api.rfqs(), []);
  const { list, name } = useCompanies();
  const navigate = useNavigate();
  const [creating, setCreating] = useState(() => new URLSearchParams(window.location.search).has("new"));
  const suppliers = list.filter((c) => c.kind === "supplier");

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Requests</h1><p className="muted">Each request is a bill of materials sent to invited suppliers.</p></div>
        <button className="btn btn-primary" onClick={() => setCreating(true)}><Icon name="plus" size={14} /> New request</button>
      </div>
      <Card>
        {rfqs.loading && !rfqs.data ? <Loading /> : rfqs.error ? <ErrorState message={rfqs.error} onRetry={rfqs.reload} /> :
          rfqs.data!.length === 0
            ? <Empty title="No requests yet" action={<button className="btn btn-primary" onClick={() => setCreating(true)}>Create a request</button>}>Create a request to start comparing supplier offers.</Empty>
            : <RfqTable rfqs={rfqs.data!} to={(r) => `/buyer/rfq/${r.id}`} role="buyer" name={name} />}
      </Card>
      {creating && suppliers.length > 0 && (
        <CreateRfqDrawer suppliers={suppliers} onClose={() => setCreating(false)}
          onCreated={(r) => { setCreating(false); navigate(`/buyer/rfq/${r.id}`); }} />
      )}
    </div>
  );
}

export function WorkspaceRoute() {
  const { id } = useParams();
  return <div className="page">{id && <RfqWorkspace id={id} />}</div>;
}

export function BuyerSuppliers() {
  const { list } = useCompanies();
  const suppliers = list.filter((c) => c.kind === "supplier");
  const [open, setOpen] = useState<string | null>(null);
  const [items, setItems] = useState<Record<string, CatalogItem[]>>({});

  useEffect(() => {
    if (open && !items[open]) api.catalog(open).then((c) => setItems((s) => ({ ...s, [open]: c }))).catch(() => undefined);
  }, [open, items]);

  return (
    <div className="page">
      <div className="page-head"><div><h1>Suppliers</h1><p className="muted">Public catalog facts. Supplier pricing rules and floors are never shown to buyers.</p></div></div>
      <div className="supplier-grid">
        {suppliers.map((s) => (
          <Card key={s.id} title={s.name} subtitle={s.location}
            actions={<button className="btn btn-ghost btn-sm" onClick={() => setOpen(open === s.id ? null : s.id)} aria-expanded={open === s.id}>{open === s.id ? "Hide catalog" : "Catalog"}</button>}>
            <div className="badges">
              {s.verified ? <Badge tone="ok">Verified</Badge> : <Badge tone="warn">Unverified</Badge>}
              <Badge>Reliability {s.reliability_score ?? "—"}</Badge>
            </div>
            {open === s.id && (items[s.id] ? (
              <table className="table table-inner">
                <thead><tr><th>MPN</th><th className="num">Stock</th><th className="num">MOQ</th><th className="num">Lead</th><th>Specs</th></tr></thead>
                <tbody>{items[s.id].map((i) => (
                  <tr key={i.mpn}><td className="mono">{i.mpn}</td><td className="num">{num(i.stock_qty)}</td><td className="num">{i.moq}</td>
                    <td className="num">{i.lead_time_days} d</td><td className="small">{Object.entries(i.specs).map(([k, v]) => `${k}: ${v}`).join(" · ")}</td></tr>
                ))}</tbody>
              </table>
            ) : <Loading label="Loading catalog" />)}
          </Card>
        ))}
      </div>
    </div>
  );
}

export function ActivityPage() {
  const { session } = useAuth();
  const role = session!.role;
  const { name } = useCompanies();
  const rfqs = useAsync(() => (role === "buyer" ? api.rfqs() : api.sellerRfqs()), [role]);
  const started = (rfqs.data ?? []).filter((r) => r.status !== "draft");
  const [id, setId] = useState("");
  const chosen = id || started[0]?.id || "";
  const turns = useAsync<{ turns: Turn[]; offers: Awaited<ReturnType<typeof api.offers>> }>(
    () => (chosen ? Promise.all([api.turns(chosen), api.offers(chosen)]).then(([t, o]) => ({ turns: t, offers: o })) : Promise.resolve({ turns: [], offers: [] })),
    [chosen]);
  const rfq = started.find((r) => r.id === chosen);

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Activity</h1><p className="muted">The audit trail of every move: source, controller and guardrail outcome.</p></div>
        {started.length > 0 && (
          <label className="select-label">Request
            <select value={chosen} onChange={(e) => setId(e.target.value)}>
              {started.map((r) => <option key={r.id} value={r.id}>{r.title} · {r.id}</option>)}
            </select>
          </label>
        )}
      </div>
      <Card actions={<button className="btn btn-ghost btn-sm" onClick={turns.reload}><Icon name="refresh" size={14} /> Refresh</button>}>
        {rfqs.loading && !rfqs.data ? <Loading /> : !started.length ? <Empty title="No activity yet">Activity appears once a negotiation starts.</Empty>
          : turns.error ? <ErrorState message={turns.error} onRetry={turns.reload} />
          : turns.loading && !turns.data ? <Loading /> :
            <Timeline turns={turns.data?.turns ?? []} offers={turns.data?.offers ?? []} name={name}
              suppliers={role === "buyer" && rfq ? rfq.participants.filter((p) => p.side === "seller").map((p) => p.company_id) : []} />}
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ seller
export function SellerInbox() {
  const { session } = useAuth();
  const { name } = useCompanies();
  const rfqs = useAsync(() => api.sellerRfqs(), []);
  const list = rfqs.data ?? [];
  const mine = (r: Rfq) => r.participants.find((p) => p.company_id === session!.company_id);
  return (
    <div className="page">
      <Greeting title={`${greeting()}, ${session?.company_name ?? "supplier"}`}
        sub="Requests you are invited to. Your agent negotiates within your pricing rules; take over at any time."
        stats={[
          { label: "Incoming requests", value: String(list.length) },
          { label: "In negotiation", value: String(list.filter((r) => r.status === "negotiating").length) },
          { label: "You are controlling", value: String(list.filter((r) => mine(r)?.controller === "human").length), hint: "human takeover active" },
          { label: "Completed", value: String(list.filter((r) => r.status === "completed").length) },
        ]} />
      <Card title="Inbox" subtitle="Only requests the buyer has opened appear here. Buyer budgets and other suppliers are never shown.">
        {rfqs.loading && !rfqs.data ? <Loading /> : rfqs.error ? <ErrorState message={rfqs.error} onRetry={rfqs.reload} /> :
          list.length === 0 ? <Empty title="No incoming requests">When a buyer starts a negotiation you are invited to, it appears here.</Empty>
            : <RfqTable rfqs={list} to={(r) => `/seller/rfq/${r.id}`} role="seller" name={name} />}
      </Card>
    </div>
  );
}

export function SellerCatalog() {
  const products = useAsync(() => api.sellerProducts(), []);
  const [editing, setEditing] = useState<SellerProduct | "new" | null>(null);
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Catalog & pricing</h1><p className="muted">Your agent never goes below your floor. Buyers see stock and lead times, never your prices or floors.</p></div>
        <button className="btn btn-primary" onClick={() => setEditing("new")}><Icon name="plus" size={14} /> Add product</button>
      </div>
      <Card>
        {products.loading && !products.data ? <Loading /> : products.error ? <ErrorState message={products.error} onRetry={products.reload} /> :
          !products.data!.length ? <Empty title="No products">Add a product with its pricing rule.</Empty> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr>
                  <th>MPN</th><th className="num">Stock</th><th className="num">MOQ</th><th className="num">Lead</th>
                  <th className="num">List</th><th className="num">Floor</th><th>Tiers</th><th className="num">Concession / round</th><th />
                </tr></thead>
                <tbody>{products.data!.map((p) => (
                  <tr key={p.mpn}>
                    <td><div className="cell-main mono">{p.mpn}</div><div className="cell-sub">{p.description}</div></td>
                    <td className="num">{num(p.stock_qty)}</td><td className="num">{p.moq}</td><td className="num">{p.lead_time_days} d</td>
                    <td className="num">{inr(p.pricing.list_price)}</td>
                    <td className="num strong">{inr(p.pricing.floor_price)}</td>
                    <td className="small">{(p.pricing.tiers ?? []).map((t) => `≥${t.min_qty}: −${(t.discount_pct * 100).toFixed(0)}%`).join(" · ") || "—"}</td>
                    <td className="num">{p.pricing.concession_step_pct != null ? `${(p.pricing.concession_step_pct * 100).toFixed(0)}% of gap` : "—"}</td>
                    <td><button className="btn btn-ghost btn-sm" onClick={() => setEditing(p)}>Edit</button></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
      </Card>
      {editing && (
        <ProductDrawer initial={editing === "new" ? undefined : editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); products.reload(); }} />
      )}
    </div>
  );
}
