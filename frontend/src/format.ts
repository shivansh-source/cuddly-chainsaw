import type { GuardStatus, OfferStatus, Source } from "./types";

const inrFmt = new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2,
});
const inrWhole = new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 0,
});

export function inr(n: number | null | undefined, whole = false): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return (whole ? inrWhole : inrFmt).format(n);
}

export function num(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : new Intl.NumberFormat("en-IN").format(n);
}

export function pct(fraction: number | null | undefined, digits = 1): string {
  return fraction === null || fraction === undefined ? "—" : `${(fraction * 100).toFixed(digits)}%`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function time(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function longDate(d = new Date()): string {
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

export const SOURCE_LABEL: Record<Source, string> = {
  engine: "Engine",
  llm_agent: "AI agent",
  human_seller: "Human · seller",
  human_buyer: "Human · buyer",
  voice_confirmed: "Voice confirmed",
  seeded: "Seeded",
};

export function sourceLabel(source: Source, voiceMode?: string): string {
  if (source === "voice_confirmed" && voiceMode === "recorded") return "Voice · recorded call";
  if (source === "voice_confirmed" && voiceMode === "live") return "Voice · live call";
  return SOURCE_LABEL[source] ?? source;
}

export const STATUS_LABEL: Record<OfferStatus, string> = {
  proposed: "Proposed",
  accepted: "Agreed",
  flagged: "Awaiting confirmation",
  confirmed: "Override confirmed",
  countered: "Countered",
  rejected: "Rejected",
};

export const GUARD_LABEL: Record<GuardStatus, string> = {
  ok: "Validated",
  blocked: "Rejected by guardrail",
  flagged_outside_authority: "Outside authority",
  override_confirmed: "Override confirmed",
};

export function greeting(d = new Date()): string {
  const h = d.getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}
