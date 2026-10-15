// Mirrors the backend contract in the repository README. The backend is the
// source of truth; nothing here recomputes scores or eligibility.

export type Role = "buyer" | "seller";
export type Side = "buyer" | "seller";
export type Controller = "agent" | "human";
export type Source =
  | "engine" | "llm_agent" | "human_seller" | "human_buyer" | "voice_confirmed" | "seeded";
export type OfferStatus =
  | "proposed" | "accepted" | "flagged" | "confirmed" | "countered" | "rejected";
export type RfqStatus = "draft" | "open" | "negotiating" | "completed" | "cancelled";
export type GuardStatus = "ok" | "blocked" | "flagged_outside_authority" | "override_confirmed";
export type ActionType = "propose" | "counter" | "trade" | "ask" | "accept" | "walk_away";

export interface Session {
  token: string;
  role: Role;
  company_id: string;
  email: string;
  company_name?: string | null;
}

export interface Company {
  id: string;
  name: string;
  kind: "buyer" | "supplier";
  location?: string;
  verified?: boolean;
  reliability_score?: number;
}

export interface CatalogItem {
  company_id: string;
  mpn: string;
  description?: string;
  specs: Record<string, unknown>;
  stock_qty: number;
  lead_time_days: number;
  moq: number;
  tax_rate: number;
}

export interface SellerProduct extends CatalogItem {
  pricing: {
    list_price: number | null;
    floor_price: number | null;
    tiers: { min_qty: number; discount_pct: number }[] | null;
    concession_step_pct: number | null;
    max_rounds: number | null;
  };
}

export interface SpecRule {
  op: ">=" | "<=" | "==" | "in";
  value: unknown;
}

export interface RfqLine {
  mpn: string;
  qty: number;
  mandatory: boolean;
  required_specs: Record<string, SpecRule>;
}

export interface Participant {
  company_id: string;
  side: Side;
  controller: Controller;
  status: string;
}

export interface Rfq {
  id: string;
  buyer_company_id: string;
  title: string;
  budget?: number;
  budget_basis?: string;
  currency: string;
  deadline: string;
  deadline_days: number;
  status: RfqStatus;
  round: number;
  max_rounds?: number;
  engine_only?: boolean;
  lines: RfqLine[];
  participants: Participant[];
  buyer_limits?: Record<string, { target: number; ceiling: number }>;
  created_at: string;
}

export interface Offer {
  id: string;
  rfq_id: string;
  company_id: string; // the supplier of the thread, for both sides
  mpn: string;
  side: Side;
  round: number;
  version: number;
  unit_price: number;
  qty: number;
  lead_time_days?: number | null;
  tax_rate?: number;
  tax?: number;
  shipping?: number;
  total_landed_cost?: number;
  valid_until?: string;
  source: Source;
  status: OfferStatus;
  created_by: string;
  turn_id: string;
  created_at: string;
  channel?: string;
  voice_mode?: "live" | "recorded";
  call_id?: string;
  conversation_id?: string | null;
}

export interface GuardrailResult {
  status?: GuardStatus;
  reasons?: string[];
  override_reason?: string | null;
  confirmed_by?: string | null;
  event?: string;
  from?: string;
  to?: string;
  original_offer_id?: string;
}

export interface Turn {
  id: string;
  rfq_id: string;
  round: number;
  participant_id: string;
  counterparty_id: string;
  side: Side;
  mpn: string;
  controller: "agent" | "human" | "engine";
  source: Source;
  raw_llm_output: string | null;
  validated_action: {
    type: ActionType;
    mpn?: string | null;
    unit_price?: number | null;
    qty?: number | null;
    lead_time_days?: number | null;
    message?: string;
  } | null;
  guardrail_result: GuardrailResult;
  message: string;
  attempts: number;
  notes: string[];
  created_at: string;
  channel?: string;
  call_id?: string;
}

export interface RankedOffer {
  company_id: string;
  name: string;
  source: Source;
  line_sources?: Record<string, Source>;
  eligible: boolean;
  landed_cost: number | null;
  lead_time_days: number | null;
  total_score: number | null;
  breakdown: Partial<Record<"cost" | "delivery" | "reliability" | "improvement", number>>;
  improvement_pct?: number | null;
  eligibility_failures: string[];
  flags: string[];
  explanation: string;
}

export interface Recommendation {
  id: string;
  explanation: string;
  created_at: string;
  ranked: RankedOffer[];
  rejected: RankedOffer[];
}

export interface Updates {
  status: RfqStatus;
  round: number;
  offers: Offer[];
  turns: Turn[];
  cursor: string | null;
}

export interface VoiceTerms {
  mpn: string | null;
  unit_price: number;
  qty: number;
  lead_time_days: number | null;
  readback_confirmed: boolean;
}

export interface VoiceCall {
  id: string;
  rfq_id: string;
  seller_id: string;
  mode: "live" | "recorded";
  status: "initiated" | "completed" | "unconfirmed" | "failed";
  conversation_id?: string | null;
  transcript?: { role: string; message: string | null; time_in_call_secs?: number }[];
  terms?: VoiceTerms | null;
  analysis_summary?: string | null;
  offer_id?: string | null;
  guardrail_status?: GuardStatus | null;
  thread_closed?: boolean;
  unconfirmed_reason?: string | null;
  created_at: string;
  completed_at?: string;
}

export interface HumanTurnResult {
  turn_id: string;
  guardrail: GuardrailResult;
  offer: Offer | null;
  reply: Offer | null;
  events: string[];
}
