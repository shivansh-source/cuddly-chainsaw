import { useState } from "react";
import { api } from "../api";
import { dateTime, inr } from "../format";
import type { Offer, Rfq, VoiceCall } from "../types";
import { Badge, Card, Empty, Icon, useAction } from "./ui";

type StepState = "done" | "no" | "na";

/** Five distinct states. They are never collapsed into one "success". */
function steps(call: VoiceCall, offer: Offer | undefined): { label: string; state: StepState; note?: string }[] {
  const transcript = (call.transcript?.length ?? 0) > 0;
  const terms = !!call.terms;
  const validated = call.guardrail_status === "ok" || call.guardrail_status === "override_confirmed";
  return [
    { label: "Call completed", state: call.status === "initiated" || call.status === "failed" ? "no" : "done",
      note: call.status === "initiated" ? "in progress or not finished" : call.status === "failed" ? "failed" : undefined },
    { label: "Transcript received", state: transcript ? "done" : "no" },
    { label: "Terms extracted", state: terms ? "done" : "no" },
    { label: "Terms validated", state: !terms ? "na" : validated ? "done" : "no",
      note: call.guardrail_status === "flagged_outside_authority" ? "outside authority, flagged" : undefined },
    { label: "Read-back confirmed", state: !terms ? "na" : call.terms?.readback_confirmed && offer ? "done" : "no",
      note: call.unconfirmed_reason ?? undefined },
  ];
}

export function VoicePanel({ rfq, calls, offers, name, canAct, onChanged }: {
  rfq: Rfq; calls: VoiceCall[]; offers: Offer[]; name: (id: string) => string;
  canAct: boolean; onChanged: () => void;
}) {
  const sellers = rfq.participants.filter((p) => p.side === "seller").map((p) => p.company_id);
  const [seller, setSeller] = useState(sellers[0] ?? "");
  const [phone, setPhone] = useState("");
  const { busy, run } = useAction();
  const negotiating = rfq.status === "negotiating";

  return (
    <div className="stack">
      {canAct && (
        <Card title="Call a supplier" subtitle="The voice agent says it is an AI calling on behalf of the buyer, and can only speak prices the guardrail allows.">
          {!negotiating && <p className="note">Voice is available while the RFQ is negotiating.</p>}
          <div className="form-row">
            <label className="field">Supplier
              <select value={seller} onChange={(e) => setSeller(e.target.value)}>
                {sellers.map((s) => <option key={s} value={s}>{name(s)}</option>)}
              </select>
            </label>
            <button className="btn btn-ghost" disabled={!negotiating || !seller || busy !== null}
              onClick={() => run("rec", () => api.voiceRecorded(rfq.id, seller), "Recorded call loaded").then(onChanged)}>
              <Icon name="play" size={14} /> {busy === "rec" ? "Loading…" : "Replay recorded demo call"}
            </button>
          </div>
          <div className="form-row">
            <label className="field">Phone number (E.164)
              <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91XXXXXXXXXX" inputMode="tel" />
            </label>
            <button className="btn btn-primary" disabled={!negotiating || phone.length < 6 || busy !== null}
              onClick={() => run("call", () => api.voiceCall(rfq.id, seller, phone), "Call placed. Results arrive after the call ends.").then(onChanged)}>
              <Icon name="phone" size={14} /> {busy === "call" ? "Placing…" : "Place live call"}
            </button>
          </div>
          <p className="cell-sub">The recorded call is an illustrative replay and is always labeled “recorded”. A live call needs the voice provider configured on the server; if it is not, the error says so.</p>
        </Card>
      )}

      {calls.length === 0 ? (
        <Empty title="No calls yet">{canAct ? "Replay the recorded demo call or place a live call." : "Calls involving your company appear here."}</Empty>
      ) : calls.slice().reverse().map((c) => {
        const offer = offers.find((o) => o.call_id === c.id && o.status !== "accepted");
        return (
          <Card key={c.id}
            title={<span className="rec-title">{name(c.seller_id)} <Badge tone={c.mode === "recorded" ? "neutral" : "accent"}>{c.mode === "recorded" ? "Recorded call" : "Live call"}</Badge></span>}
            subtitle={`Started ${dateTime(c.created_at)}${c.completed_at ? ` · finished ${dateTime(c.completed_at)}` : ""} · outbound, buyer's voice agent`}>
            <ol className="vsteps">
              {steps(c, offer).map((s) => (
                <li key={s.label} className={`vstep vstep-${s.state}`}>
                  <span className="vstep-mark" aria-hidden="true">{s.state === "done" ? "✓" : s.state === "na" ? "–" : "○"}</span>
                  <span>{s.label}<span className="sr-only">: {s.state === "done" ? "yes" : s.state === "na" ? "not applicable" : "no"}</span></span>
                  {s.note && <span className="muted"> · {s.note}</span>}
                </li>
              ))}
            </ol>
            {c.terms && (
              <div className="terms">
                <strong>Extracted terms</strong>
                <span className="mono">{c.terms.mpn ?? "—"}</span>
                <span>{inr(c.terms.unit_price)} × {c.terms.qty}</span>
                <span>{c.terms.lead_time_days != null ? `${c.terms.lead_time_days} d lead` : "lead not stated"}</span>
                {c.thread_closed && <Badge tone="ok">Line agreed at this price</Badge>}
              </div>
            )}
            {c.analysis_summary && <p className="muted">{c.analysis_summary}</p>}
            {c.transcript && c.transcript.length > 0 && (
              <details className="transcript" open={calls.length === 1}>
                <summary>Transcript ({c.transcript.length} lines)</summary>
                <ol>
                  {c.transcript.map((line, i) => (
                    <li key={i}>
                      <span className="who">{line.role === "agent" ? "Voice agent" : "Supplier"}</span>
                      {line.time_in_call_secs != null && <span className="muted mono">{line.time_in_call_secs}s</span>}
                      <span>{line.message}</span>
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </Card>
        );
      })}
    </div>
  );
}
