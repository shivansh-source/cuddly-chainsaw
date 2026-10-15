import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";
import type { Offer, Recommendation, Rfq, Turn, VoiceCall } from "./types";

export interface Async<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): Async<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : "Something went wrong"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: useCallback(() => setTick((t) => t + 1), []) };
}

function mergeById<T extends { id: string }>(prev: T[], next: T[]): T[] {
  if (!next.length) return prev;
  const map = new Map(prev.map((x) => [x.id, x]));
  for (const x of next) map.set(x.id, x);
  return Array.from(map.values());
}

export interface RfqLive {
  rfq: Rfq | null;
  offers: Offer[];
  turns: Turn[];
  calls: VoiceCall[];
  rec: Recommendation | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const POLL_MS = 2500;

/** One RFQ, kept current by polling the backend's `/updates` cursor. */
export function useRfqLive(id: string | undefined, wantRecommendation: boolean): RfqLive {
  const [rfq, setRfq] = useState<Rfq | null>(null);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [calls, setCalls] = useState<VoiceCall[]>([]);
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const cursor = useRef<string | null>(null);
  const stamp = useRef<string>("");

  const loadSide = useCallback(async (r: Rfq) => {
    const [c, recommendation] = await Promise.all([
      api.voiceCalls(r.id).catch(() => [] as VoiceCall[]),
      wantRecommendation && r.status === "completed"
        ? api.recommendation(r.id).catch((e) => (e instanceof ApiError && e.status === 404 ? null : Promise.reject(e)))
        : Promise.resolve(null),
    ]);
    setCalls(c);
    setRec(recommendation);
  }, [wantRecommendation]);

  const refresh = useCallback(async () => {
    if (!id) return;
    const [r, u] = await Promise.all([api.rfq(id), api.updates(id)]);
    cursor.current = u.cursor;
    stamp.current = `${r.status}|${r.round}`;
    setRfq(r);
    setOffers(u.offers);
    setTurns(u.turns);
    await loadSide(r);
  }, [id, loadSide]);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    setLoading(true);
    setError(null);
    setRfq(null);
    setOffers([]);
    setTurns([]);
    setRec(null);
    setCalls([]);
    refresh()
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => alive && setLoading(false));

    const timer = window.setInterval(async () => {
      if (document.hidden) return;
      try {
        const u = await api.updates(id, cursor.current);
        const changed = u.offers.length || u.turns.length || `${u.status}|${u.round}` !== stamp.current;
        if (!alive || !changed) return;
        cursor.current = u.cursor ?? cursor.current;
        setOffers((p) => mergeById(p, u.offers));
        setTurns((p) => mergeById(p, u.turns));
        const r = await api.rfq(id);
        if (!alive) return;
        stamp.current = `${r.status}|${r.round}`;
        setRfq(r);
        await loadSide(r);
      } catch {
        /* transient polling failure: the next tick retries */
      }
    }, POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [id, refresh, loadSide]);

  return { rfq, offers, turns, calls, rec, loading, error, refresh };
}
