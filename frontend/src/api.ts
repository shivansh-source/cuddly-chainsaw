import type {
  ActionType, CatalogItem, Company, HumanTurnResult, Offer, Recommendation, Rfq, RfqLine,
  SellerProduct, Session, Turn, Updates, VoiceCall,
} from "./types";

export const API_BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
const SESSION_KEY = "negotiator.session";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function saveSession(session: Session | null): void {
  try {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable: session lives only in memory */
  }
}

let token: string | null = loadSession()?.token ?? null;
export function setToken(value: string | null): void {
  token = value;
}

function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join("; ");
  }
  return "Request failed";
}

async function request<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers: { ...headers, ...(init.headers as object) } });
  } catch {
    throw new ApiError(0, "Cannot reach the server. It may be starting up; try again in a moment.");
  }
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && auth) window.dispatchEvent(new Event("negotiator:unauthorized"));
    throw new ApiError(res.status, detailText(body?.detail));
  }
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export interface TurnInput {
  mpn: string;
  type: ActionType;
  unit_price?: number;
  qty?: number;
  lead_time_days?: number;
  message?: string;
  seller_id?: string;
}

export interface RfqInput {
  title: string;
  budget: number;
  budget_basis: "landed_incl_tax" | "pre_tax";
  currency: string;
  deadline_days: number;
  max_rounds: number;
  lines: RfqLine[];
  invite: string[];
}

export interface ProductInput {
  mpn: string;
  description: string;
  specs: Record<string, unknown>;
  stock_qty: number;
  lead_time_days: number;
  moq: number;
  tax_rate: number;
  list_price: number;
  floor_price: number;
  tiers: { min_qty: number; discount_pct: number }[];
  concession_step_pct: number;
  max_rounds: number;
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; role: "buyer" | "seller"; company_id: string }>(
      "/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }, false),
  me: () => request<{ email: string; role: string; company_id: string; company_name: string | null }>("/auth/me"),
  health: () => request<{ ok: boolean; llm: string }>("/health", {}, false),

  companies: () => request<Company[]>("/companies"),
  catalog: (companyId: string) => request<CatalogItem[]>(`/companies/${companyId}/catalog`),

  rfqs: () => request<Rfq[]>("/rfqs"),
  rfq: (id: string) => request<Rfq>(`/rfqs/${id}`),
  createRfq: (input: RfqInput) => post<Rfq>("/rfqs", input),
  start: (id: string, opts: { run_all?: boolean; engine_only?: boolean }) =>
    post<{ status: string; round?: number; recommendation?: Recommendation }>(`/rfqs/${id}/start`, opts),
  nextRound: (id: string) =>
    post<{ status: string; round: number; recommendation?: Recommendation }>(`/rfqs/${id}/rounds`),
  recommendation: (id: string) => request<Recommendation>(`/rfqs/${id}/recommendation`),
  offers: (id: string) => request<Offer[]>(`/rfqs/${id}/offers`),
  turns: (id: string) => request<Turn[]>(`/rfqs/${id}/turns`),
  updates: (id: string, since?: string | null) =>
    request<Updates>(`/rfqs/${id}/updates${since ? `?since=${encodeURIComponent(since)}` : ""}`),
  handover: (id: string, controller: "agent" | "human") =>
    post<{ company_id: string; controller: string }>(`/rfqs/${id}/handover`, { controller }),
  humanTurn: (id: string, input: TurnInput) => post<HumanTurnResult>(`/rfqs/${id}/turns`, input),
  confirm: (id: string, offerId: string, reason: string) =>
    post<Offer>(`/rfqs/${id}/confirm`, { offer_id: offerId, reason }),

  voiceCalls: (id: string) => request<VoiceCall[]>(`/rfqs/${id}/voice`),
  voiceRecorded: (id: string, sellerId: string) =>
    post<{ call_id: string; status: string }>(`/rfqs/${id}/voice/recorded`, { seller_id: sellerId }),
  voiceSession: (id: string, sellerId: string) =>
    post<{
      call_id: string; session_token: string; signed_url: string | null; browser_voice_error: string | null;
      dynamic_variables: Record<string, string | number | boolean>;
    }>(`/rfqs/${id}/voice/session`, { seller_id: sellerId }),
  voiceFinalize: (id: string, callId: string, conversationId: string | null) =>
    post<{ status: string; reason?: string | null; idempotent?: boolean }>(
      `/rfqs/${id}/voice/${callId}/finalize`, { conversation_id: conversationId }),
  voiceCall: (id: string, sellerId: string, toNumber: string) =>
    post<{ call_id: string; conversation_id: string | null }>(`/rfqs/${id}/voice/call`,
      { seller_id: sellerId, to_number: toNumber }),

  sellerRfqs: () => request<Rfq[]>("/seller/rfqs"),
  sellerProducts: () => request<SellerProduct[]>("/seller/products"),
  upsertProduct: (input: ProductInput) => post<{ mpn: string }>("/seller/products", input),
};
