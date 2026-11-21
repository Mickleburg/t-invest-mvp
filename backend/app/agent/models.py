from typing import Literal
from pydantic import Field
from backend.app.common import StrictModel


class Number(StrictModel):
    value: str = Field(max_length=40)
    quote: str = Field(min_length=1,max_length=1000)


class Currency(StrictModel):
    value: Literal['rub','usd','eur','points']
    quote: str = Field(min_length=1,max_length=1000)


class RiskInputs(StrictModel):
    instrument_kind: Literal['share','future','unknown']
    instrument_id: str | None
    direction: Literal['long','short','unknown']
    capital: Number | None
    capital_currency: Currency | None
    price_currency: Currency | None
    risk_percent: Number | None
    entry: Number | None
    stop: Number | None
    target: Number | None
    quantity: Number | None
    lot_size: Number | None
    point_value: Number | None
    point_value_currency: Currency | None
    costs_per_unit: Number | None


class Plan(StrictModel):
    status: Literal['exploring','preliminary','reviewable']
    instrument: str | None
    direction: str | None
    hypothesis: str
    basis: list[str] = Field(max_length=5)
    counterarguments: list[str] = Field(max_length=5)
    horizon: str | None
    entry: str | None
    confirmation: list[str] = Field(max_length=5)
    invalidation: list[str] = Field(max_length=5)
    exit: str | None
    risk_notes: list[str] = Field(max_length=5)
    missing: list[str] = Field(max_length=8)


class ToolRequest(StrictModel):
    kind: Literal['search','quote','history','news','spec','web']
    query: str | None = Field(max_length=180)
    instrument_id: str | None
    question: str | None = Field(max_length=500)


class Fact(StrictModel):
    statement: str = Field(max_length=800)
    evidence_id: str


class Reply(StrictModel):
    reply: str = Field(min_length=1,max_length=4500)
    questions: list[str] = Field(max_length=2)
    plan: Plan | None
    risk_inputs: RiskInputs | None
    facts: list[Fact] = Field(max_length=6)
    tool_requests: list[ToolRequest] = Field(max_length=2)
