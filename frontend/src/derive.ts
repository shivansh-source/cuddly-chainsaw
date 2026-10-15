// Display-only selection over backend data (which offer is latest, which are
// flagged). Totals come from the backend's own `total_landed_cost` per offer;
// scores and eligibility come only from the recommendation.
import type { Offer, Rfq, Source } from "./types";

export const COUNTING: Offer["status"][] = ["proposed", "accepted", "confirmed"];

const byRecency = (a: Offer, b: Offer) =>
  b.round - a.round || b.version - a.version || b.created_at.localeCompare(a.created_at);

export function thread(offers: Offer[], supplier: string, mpn: string): Offer[] {
  return offers.filter((o) => o.company_id === supplier && o.mpn === mpn);
}

export function agreed(offers: Offer[], supplier: string, mpn: string): Offer | null {
  return thread(offers, supplier, mpn).find((o) => o.status === "accepted") ?? null;
}

export function latest(offers: Offer[], supplier: string, mpn: string, side: "buyer" | "seller"): Offer | null {
  const list = thread(offers, supplier, mpn)
    .filter((o) => o.side === side && COUNTING.includes(o.status) && o.status !== "accepted")
    .sort(byRecency);
  return list[0] ?? null;
}

export function opening(offers: Offer[], supplier: string, mpn: string): Offer | null {
  const list = thread(offers, supplier, mpn)
    .filter((o) => o.side === "seller" && o.round === 0 && COUNTING.includes(o.status))
    .sort((a, b) => a.version - b.version);
  return list[0] ?? null;
}

/** The price that currently stands on a line: the agreed deal, else the latest valid ask. */
export function current(offers: Offer[], supplier: string, mpn: string): Offer | null {
  return agreed(offers, supplier, mpn) ?? latest(offers, supplier, mpn, "seller");
}

export function flagged(offers: Offer[]): Offer[] {
  const confirmedTurns = new Set<string>();
  // A confirmation appends a new version; the flagged original stays. Treat a
  // flagged offer as resolved once a later confirmed version of the same
  // price exists on the same thread and side.
  for (const o of offers) if (o.status === "confirmed") confirmedTurns.add(`${o.company_id}|${o.mpn}|${o.side}|${o.unit_price}`);
  return offers.filter(
    (o) => o.status === "flagged" && !confirmedTurns.has(`${o.company_id}|${o.mpn}|${o.side}|${o.unit_price}`));
}

export interface LineView {
  mpn: string;
  qty: number;
  current: Offer | null;
  opening: Offer | null;
  bid: Offer | null;
  agreed: boolean;
}

export interface SupplierRow {
  supplier: string;
  lines: LineView[];
  quotedLines: number;
  landed: number | null; // sum of backend total_landed_cost over quoted lines
  lead: number | null;
  round: number | null;
  sources: Source[];
  allAgreed: boolean;
  pendingFlags: number;
}

export function supplierRows(rfq: Rfq, offers: Offer[]): SupplierRow[] {
  const pending = flagged(offers);
  return rfq.participants
    .filter((p) => p.side === "seller")
    .map((p) => {
      const lines: LineView[] = rfq.lines.map((ln) => ({
        mpn: ln.mpn,
        qty: ln.qty,
        current: current(offers, p.company_id, ln.mpn),
        opening: opening(offers, p.company_id, ln.mpn),
        bid: latest(offers, p.company_id, ln.mpn, "buyer"),
        agreed: agreed(offers, p.company_id, ln.mpn) !== null,
      }));
      const quoted = lines.filter((l) => l.current);
      const leads = quoted.map((l) => l.current!.lead_time_days).filter((v): v is number => typeof v === "number");
      const landedParts = quoted.map((l) => l.current!.total_landed_cost);
      return {
        supplier: p.company_id,
        lines,
        quotedLines: quoted.length,
        landed: quoted.length && landedParts.every((v) => typeof v === "number")
          ? (landedParts as number[]).reduce((a, b) => a + b, 0) : null,
        lead: leads.length === quoted.length && leads.length ? Math.max(...leads) : null,
        round: quoted.length ? Math.max(...quoted.map((l) => l.current!.round)) : null,
        sources: Array.from(new Set(quoted.map((l) => l.current!.source))),
        allAgreed: lines.length > 0 && lines.every((l) => l.agreed),
        pendingFlags: pending.filter((o) => o.company_id === p.company_id).length,
      };
    });
}

export function maxRounds(rfq: Rfq): number {
  return rfq.max_rounds ?? 3;
}
