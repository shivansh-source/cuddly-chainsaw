"""Typed contracts for the deterministic engine.

The LLM layer (Phase 2) parses its output into `Action`; nothing the model
writes is trusted until the guardrail has checked it against an authority.
"""
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Side = Literal["buyer", "seller"]
Controller = Literal["agent", "human"]
Source = Literal[
    "engine", "llm_agent", "human_seller", "human_buyer", "voice_confirmed", "seeded"
]
ActionType = Literal["propose", "counter", "trade", "ask", "accept", "walk_away"]
GuardStatus = Literal["ok", "blocked", "flagged_outside_authority", "override_confirmed"]

# Action types that carry a price and therefore must pass authority checks.
PRICED_ACTIONS: frozenset[str] = frozenset({"propose", "counter", "trade", "accept"})


class Tier(BaseModel):
    min_qty: int = Field(ge=1)
    discount_pct: float = Field(ge=0, le=1)


class PricingRule(BaseModel):
    mpn: str
    list_price: float = Field(ge=0)
    floor_price: float = Field(ge=0)
    tiers: list[Tier] = []
    concession_step_pct: float = Field(ge=0, le=1)
    max_rounds: int = Field(ge=1, default=3)

    @model_validator(mode="after")
    def _floor_not_above_list(self) -> "PricingRule":
        if self.floor_price > self.list_price:
            raise ValueError("floor_price cannot exceed list_price")
        return self


class Participant(BaseModel, frozen=True):
    company_id: str
    side: Side
    controller: Controller

    def with_controller(self, controller: Controller) -> "Participant":
        """Take over / hand back. Returns a new value; history is untouched."""
        return self.model_copy(update={"controller": controller})


class Action(BaseModel):
    """A move proposed by either side. `message` is data, never instructions."""

    type: ActionType
    mpn: str | None = None
    unit_price: float | None = None
    qty: int | None = None
    lead_time_days: int | None = None
    message: str = ""

    @field_validator("unit_price")
    @classmethod
    def _positive_price(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("unit_price must be positive")
        return v

    @field_validator("qty")
    @classmethod
    def _positive_qty(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("qty must be at least 1")
        return v


class SellerAuthority(BaseModel):
    mpn: str
    floor_price: float
    moq: int
    stock_qty: int
    lead_time_days: int  # catalog default, used when the action omits it
    deadline_days: int


class BuyerAuthority(BaseModel):
    mpn: str
    line_qty: int
    max_unit_price: float


class GuardrailResult(BaseModel):
    status: GuardStatus
    reasons: list[str] = []
    override_reason: str | None = None
    confirmed_by: str | None = None

    @property
    def allowed(self) -> bool:
        """Whether the action enters the thread at all."""
        return self.status != "blocked"

    @property
    def requires_confirmation(self) -> bool:
        return self.status == "flagged_outside_authority"

    @property
    def counts(self) -> bool:
        """Whether the action may be used as a real offer (scoring, acceptance)."""
        return self.status in ("ok", "override_confirmed")


class BuyerLimit(BaseModel):
    mpn: str
    target: float   # soft goal the buyer opens toward
    ceiling: float  # hard cap: the buyer never offers above this


class RfqLineReq(BaseModel):
    mpn: str
    qty: int
    required_specs: dict[str, dict[str, Any]] = {}
    mandatory: bool = True


class LineQuote(BaseModel):
    mpn: str
    unit_price: float
    qty: int
    moq: int | None = None
    stock_qty: int | None = None
    lead_time_days: int | None = None
    tax_rate: float = 0.0
    shipping: float = 0.0
    discount: float = 0.0
    specs: dict[str, Any] = {}
    initial_unit_price: float | None = None  # round-0 quote, same qty and terms


class SupplierQuote(BaseModel):
    company_id: str
    name: str = ""
    reliability_score: float | None = None
    source: Source = "engine"
    lines: list[LineQuote]


class RankedOffer(BaseModel):
    company_id: str
    name: str = ""
    source: Source
    eligible: bool
    landed_cost: float | None = None
    lead_time_days: int | None = None
    total_score: float | None = None
    breakdown: dict[str, float] = {}
    improvement_pct: float | None = None
    eligibility_failures: list[str] = []
    flags: list[str] = []
    explanation: str = ""


class Recommendation(BaseModel):
    ranked: list[RankedOffer]    # eligible, best first
    rejected: list[RankedOffer]  # ineligible, with reasons; never silently dropped
