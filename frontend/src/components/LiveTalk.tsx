import type { Conversation } from "@elevenlabs/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import type { Rfq } from "../types";
import { Badge, Icon } from "./ui";

type Phase = "idle" | "starting" | "live" | "finishing";
interface Line { who: "agent" | "you"; text: string }

/** Talk to the buyer's voice agent from the browser, playing the supplier's rep.
 *  Everything shown here comes from real SDK events; nothing is simulated. */
export function LiveTalk({ rfq, seller, sellerName, onFinished }: {
  rfq: Rfq; seller: string; sellerName: string; onFinished: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [mode, setMode] = useState<"speaking" | "listening" | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const conv = useRef<Conversation | null>(null);
  const callId = useRef<string | null>(null);
  const convId = useRef<string | null>(null);
  const finishing = useRef(false);

  const finalize = useCallback(async () => {
    if (finishing.current || !callId.current) return;
    finishing.current = true;
    setPhase("finishing");
    setMode(null);
    try {
      let result: { status: string; reason?: string | null } | null = null;
      for (let attempt = 0; attempt < 4 && !result; attempt++) {
        try {
          result = await api.voiceFinalize(rfq.id, callId.current, convId.current);
        } catch (e) {
          // 409: ElevenLabs is still analysing the call. Wait and retry.
          if (e instanceof ApiError && e.status === 409 && attempt < 3) await new Promise((r) => setTimeout(r, 5000));
          else throw e;
        }
      }
      setOutcome(result?.status === "completed"
        ? "Call finalized: confirmed terms were validated and recorded."
        : `Call closed without a confirmed offer${result?.reason ? `: ${result.reason}` : "."}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not finalize the call");
    } finally {
      conv.current = null;
      callId.current = null;
      convId.current = null;
      finishing.current = false;
      setPhase("idle");
      onFinished();
    }
  }, [rfq.id, onFinished]);

  const start = async () => {
    setError(null);
    setOutcome(null);
    setLines([]);
    setPhase("starting");
    try {
      const s = await api.voiceSession(rfq.id, seller);
      callId.current = s.call_id;
      if (!s.signed_url) {
        setError(s.browser_voice_error ?? "Browser voice is not available.");
        await finalize();
        return;
      }
      try {
        await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        setError("Microphone access was blocked. Allow it in the browser and try again.");
        await finalize();
        return;
      }
      const { Conversation: Voice } = await import("@elevenlabs/client");
      conv.current = await Voice.startSession({
        signedUrl: s.signed_url,
        dynamicVariables: s.dynamic_variables,
        onConnect: ({ conversationId }) => {
          convId.current = conversationId;
          setPhase("live");
        },
        onMessage: (m) => {
          const who = m.source === "ai" ? "agent" : "you";
          setLines((ls) => [...ls, { who, text: m.message }]);
        },
        onModeChange: ({ mode: next }) => setMode(next === "speaking" ? "speaking" : "listening"),
        onError: (message) => setError(String(message)),
        onDisconnect: () => {
          void finalize();
        },
      });
      convId.current = convId.current ?? conv.current.getId();
      setPhase("live");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the call");
      await finalize();
    }
  };

  const end = async () => {
    try {
      await conv.current?.endSession();
    } finally {
      await finalize();
    }
  };

  // Leaving the page mid-call ends the session; the backend still finalizes on the next visit or via webhook.
  useEffect(() => () => {
    void conv.current?.endSession();
  }, []);

  return (
    <div className="live">
      <div className="live-head">
        <div>
          <strong>Talk to the agent in your browser</strong>
          <p className="cell-sub">You play {sellerName}'s sales rep. The agent is the buyer's AI and can only offer prices the guardrail allows. Agree on a price and confirm the read-back to create a voice-confirmed offer.</p>
        </div>
        {phase === "live" && (
          <Badge tone={mode === "speaking" ? "accent" : "info"}>{mode === "speaking" ? "Agent speaking" : "Listening to you"}</Badge>
        )}
        {phase === "finishing" && <Badge>Processing call…</Badge>}
      </div>

      <div className="form-actions" style={{ justifyContent: "flex-start" }}>
        {phase === "idle" && (
          <button className="btn btn-primary" disabled={rfq.status !== "negotiating"} onClick={start}>
            <Icon name="phone" size={14} /> Start talking
          </button>
        )}
        {phase === "starting" && <button className="btn btn-primary" disabled>Connecting…</button>}
        {phase === "live" && <button className="btn btn-dark" onClick={end}>End call</button>}
        {phase === "finishing" && <span className="muted">Fetching the transcript and extracted terms from ElevenLabs. This can take up to a minute.</span>}
      </div>

      {error && <p className="form-error" role="alert">{error}</p>}
      {outcome && <p className="note">{outcome}</p>}

      {lines.length > 0 && (
        <ol className="live-lines" aria-live="polite">
          {lines.map((l, i) => (
            <li key={i} className={`live-${l.who}`}>
              <span className="who">{l.who === "agent" ? "Agent" : "You"}</span>
              <span>{l.text}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
