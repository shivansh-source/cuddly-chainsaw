import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import { Badge, Icon } from "../components/ui";
import { inr } from "../format";

// Figures from the seeded demo request (rfq_demo_1) run with the deterministic
// engine. Shown as a labeled illustration, never as live results.
const PREVIEW = {
  ranked: [
    { name: "Volt Components", landed: 86439.72, lead: 3, score: 88.65, tag: "Recommended" },
    { name: "Silicon Mart", landed: 89251.66, lead: 4, score: 83.86, tag: "Eligible" },
  ],
  rejected: { name: "Circuit Bazaar", reason: "USB4105-GF-A: lead time 21d beyond deadline 14d" },
  path: [
    { round: 0, ask: 342.0, bid: 305.8 },
    { round: 1, ask: 330.25, bid: 318.08 },
    { round: 2, ask: 318.5, bid: 318.5 },
  ],
};

const CAPABILITIES = [
  { icon: "shield", title: "Negotiate within limits",
    text: "Every agent offer is checked by deterministic rules before it counts. Out-of-authority moves are blocked or flagged." },
  { icon: "requests", title: "Compare the real cost",
    text: "Landed cost includes quantity, tax and shipping. MOQ, stock, specs and delivery deadline decide eligibility." },
  { icon: "activity", title: "Verify every recommendation",
    text: "Trace each price to its source, round, negotiation turn and validation result." },
];

export function Landing() {
  const { session } = useAuth();
  const home = session ? (session.role === "buyer" ? "/buyer" : "/seller") : null;
  const startTo = session?.role === "buyer" ? "/buyer/requests?new=1" : "/login?next=/buyer/requests%3Fnew%3D1";
  const sampleTo = session?.role === "buyer" ? "/buyer/rfq/rfq_demo_1" : "/login?sample=1";

  return (
    <div className="landing">
      <header className="lp-header">
        <div className="lp-brand">
          <span className="brand"><span className="brand-mark" aria-hidden="true">N</span>The Negotiator</span>
          <span className="lp-desc">AI Procurement Operations</span>
        </div>
        {home
          ? <Link className="btn btn-dark" to={home}>Open workspace</Link>
          : <Link className="btn btn-ghost" to="/login">Sign in</Link>}
      </header>

      <main className="lp-main">
        <section className="lp-hero">
          <div className="lp-copy">
            <h1>Get better supplier offers. Keep every decision in your control.</h1>
            <p className="lp-lead">
              Negotiate electronic-component purchases with AI agents, validate every offer against defined limits,
              and compare suppliers using landed cost, delivery, and an auditable evidence trail.
            </p>
            <div className="lp-ctas">
              <Link className="btn btn-primary lp-btn" to={startTo}>Start a negotiation</Link>
              <Link className="btn btn-ghost lp-btn" to={sampleTo}>Explore a sample RFQ</Link>
            </div>
            <p className="muted lp-flow">Create RFQ → Negotiate → Validate → Compare → Recommend</p>
          </div>

          <figure className="lp-preview" aria-label="Product preview">
            <div className="lp-preview-head">
              <div>
                <strong>Sensor node batch</strong>
                <span className="muted"> · 100 ESP32 · 100 BME280 · 200 USB-C</span>
              </div>
              <Badge>Illustrative · seeded demo run</Badge>
            </div>

            <div className="lp-rows">
              {PREVIEW.ranked.map((r, i) => (
                <div key={r.name} className={`lp-row ${i === 0 ? "lp-row-lead" : ""}`}>
                  <span className="lp-rank">{i + 1}</span>
                  <span className="lp-name">{r.name}</span>
                  <span className="num">{inr(r.landed)}</span>
                  <span className="num muted">{r.lead} d</span>
                  <span className="num">{r.score.toFixed(2)}</span>
                  <Badge tone="ok">{r.tag}</Badge>
                </div>
              ))}
              <div className="lp-row lp-row-rej">
                <span className="lp-rank">–</span>
                <span className="lp-name">{PREVIEW.rejected.name}</span>
                <span className="lp-reason">{PREVIEW.rejected.reason}</span>
                <Badge tone="err">Not eligible</Badge>
              </div>
            </div>

            <div className="lp-path">
              <span className="label">Volt · ESP32-WROOM-32E · price by round</span>
              <div className="lp-rounds">
                {PREVIEW.path.map((p) => (
                  <div key={p.round} className="lp-round">
                    <span className="muted">Round {p.round}</span>
                    <span>Ask <strong>{inr(p.ask)}</strong></span>
                    {p.ask === p.bid
                      ? <Badge tone="ok">Buyer accepted</Badge>
                      : <span className="muted">Bid {inr(p.bid)}</span>}
                  </div>
                ))}
              </div>
            </div>

            <figcaption className="lp-evidence">
              <Icon name="shield" size={14} />
              Each price above links to its offer, negotiation turn and guardrail result in the workspace.
            </figcaption>
          </figure>
        </section>

        <section className="lp-caps" aria-label="Capabilities">
          {CAPABILITIES.map((c) => (
            <div key={c.title} className="lp-cap">
              <span className="lp-cap-icon"><Icon name={c.icon} /></span>
              <div>
                <h2>{c.title}</h2>
                <p className="muted">{c.text}</p>
              </div>
            </div>
          ))}
        </section>
      </main>
    </div>
  );
}
