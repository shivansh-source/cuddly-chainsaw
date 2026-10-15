import { useMemo, useState } from "react";
import { COUNTING } from "../derive";
import { inr } from "../format";
import type { Offer } from "../types";

export const SERIES_COLORS = ["#f2622e", "#16171a", "#5b8def", "#2f9e8f", "#a0896b", "#8b6fd1"];

interface Point { round: number; price: number }
interface Series { supplier: string; color: string; asks: Point[]; bids: Point[]; deal: Point | null }

const W = 640, H = 240, PAD = { l: 64, r: 16, t: 14, b: 34 };

function latestPerRound(offers: Offer[]): Point[] {
  const byRound = new Map<number, Offer>();
  for (const o of offers) {
    const cur = byRound.get(o.round);
    if (!cur || o.version > cur.version) byRound.set(o.round, o);
  }
  return Array.from(byRound.values()).sort((a, b) => a.round - b.round).map((o) => ({ round: o.round, price: o.unit_price }));
}

/** Supplier asks per round for one part, from real offers only. */
export function PriceChart({ offers, mpn, suppliers, name, maxRound, showBids }: {
  offers: Offer[]; mpn: string; suppliers: string[]; name: (id: string) => string;
  maxRound: number; showBids: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);

  const series: Series[] = useMemo(() => suppliers.map((s, i) => {
    const mine = offers.filter((o) => o.company_id === s && o.mpn === mpn);
    const deal = mine.find((o) => o.status === "accepted");
    return {
      supplier: s,
      color: SERIES_COLORS[i % SERIES_COLORS.length],
      asks: latestPerRound(mine.filter((o) => o.side === "seller" && COUNTING.includes(o.status) && o.status !== "accepted")),
      bids: latestPerRound(mine.filter((o) => o.side === "buyer" && o.status === "proposed")),
      deal: deal ? { round: deal.round, price: deal.unit_price } : null,
    };
  }), [offers, mpn, suppliers]);

  const all = series.flatMap((s) => [...s.asks, ...(showBids ? s.bids : [])]);
  if (all.length < 2) {
    return <p className="muted chart-empty">Not enough offers yet to chart prices for {mpn}. Prices appear here as rounds are played.</p>;
  }
  const rounds = Math.max(maxRound, ...all.map((p) => p.round));
  let lo = Math.min(...all.map((p) => p.price)), hi = Math.max(...all.map((p) => p.price));
  if (hi === lo) { hi += 1; lo -= 1; }
  const span = hi - lo; lo -= span * 0.08; hi += span * 0.08;
  const x = (r: number) => PAD.l + (rounds ? (r / rounds) * (W - PAD.l - PAD.r) : 0);
  const y = (p: number) => PAD.t + (1 - (p - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const path = (pts: Point[]) => pts.map((p, i) => `${i ? "L" : "M"}${x(p.round).toFixed(1)},${y(p.price).toFixed(1)}`).join(" ");
  const ticks = [0, 1, 2, 3].map((i) => lo + ((hi - lo) * i) / 3);

  const hoverRows = hover === null ? [] : series.flatMap((s) => {
    const ask = s.asks.find((p) => p.round === hover);
    const bid = showBids ? s.bids.find((p) => p.round === hover) : undefined;
    return ask || bid ? [{ s, ask, bid }] : [];
  });

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Unit price by round for ${mpn}`}
        onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={PAD.l - 8} y={y(t) + 4} textAnchor="end" className="axis">{inr(t, t > 100)}</text>
          </g>
        ))}
        {Array.from({ length: rounds + 1 }, (_, r) => (
          <g key={r}>
            <text x={x(r)} y={H - 10} textAnchor="middle" className="axis">Round {r}</text>
            <rect x={x(r) - (W - PAD.l - PAD.r) / (rounds * 2 || 2)} y={PAD.t} height={H - PAD.t - PAD.b}
              width={(W - PAD.l - PAD.r) / (rounds || 1)} fill="transparent" onMouseEnter={() => setHover(r)} />
          </g>
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={H - PAD.b} className="hover-line" />}
        {series.map((s) => (
          <g key={s.supplier} pointerEvents="none">
            {showBids && s.bids.length > 0 && (
              <path d={path(s.bids)} fill="none" stroke={s.color} strokeWidth={1.4} strokeDasharray="4 4" opacity={0.7} />
            )}
            {s.asks.length > 0 && <path d={path(s.asks)} fill="none" stroke={s.color} strokeWidth={2} />}
            {s.asks.map((p) => <circle key={p.round} cx={x(p.round)} cy={y(p.price)} r={3.2} fill={s.color} />)}
            {s.deal && (
              <circle cx={x(s.deal.round)} cy={y(s.deal.price)} r={7} fill="none" stroke={s.color} strokeWidth={2} />
            )}
          </g>
        ))}
      </svg>
      {hover !== null && hoverRows.length > 0 && (
        <div className="chart-tip" role="status">
          <strong>Round {hover}</strong>
          {hoverRows.map(({ s, ask, bid }) => (
            <div key={s.supplier}>
              <span className="dot" style={{ background: s.color }} /> {name(s.supplier)}: {ask ? inr(ask.price) : "—"}
              {bid && <span className="muted"> · bid {inr(bid.price)}</span>}
            </div>
          ))}
        </div>
      )}
      <div className="legend">
        {series.filter((s) => s.asks.length).map((s) => (
          <span key={s.supplier}><span className="dot" style={{ background: s.color }} />{name(s.supplier)}</span>
        ))}
        <span className="muted">Solid: supplier ask{showBids ? " · dashed: buyer bid" : ""} · ring: agreed price</span>
      </div>
    </div>
  );
}
