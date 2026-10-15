"""Reset the demo to a known-good state and pre-run one auction.

  * rfq_demo_1 (Acme) is left in `draft` so the live demo starts clean.
  * rfq_demo_2 (Nimbus) is pre-run with the deterministic engine, so a seller
    or buyer logging in sees real history, offers and a recommendation.

Engine-only runs never call the LLM, so this output is identical every time.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_db  # noqa: E402
from app.negotiation.orchestrator import Orchestrator  # noqa: E402
from scripts.seed import main as seed  # noqa: E402


def main() -> None:
    seed()
    rec = Orchestrator(get_db(), llm=None).run_all("rfq_demo_2", engine_only=True)
    print("\npre-run rfq_demo_2:", rec["explanation"])
    print("rfq_demo_1 left in draft for the live demo.")


if __name__ == "__main__":
    main()
