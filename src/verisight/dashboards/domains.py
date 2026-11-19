"""Recognise a table's subject area from its relation and column names.

The result only chooses which measures lead a dashboard and how it is titled.
It reads names, not values, is never sent to a model, and never changes a
number. A table that matches no area clearly stays ``general``.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

_TOKEN = re.compile(r"[A-Z]+(?![a-z])\d*|[A-Z]?[a-z]+\d*|\d+")
_NOT_PLURAL = ("ss", "is", "us")
_MIN_MATCHES = 2
_STRONG_MATCHES = 3


@dataclass(frozen=True, slots=True)
class Domain:
    """One subject area: the names that signal it and its leading measures."""

    key: str
    label: str
    focus: str
    keywords: frozenset[str]
    measures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DomainMatch:
    """Which area was recognised, and the name parts that led to it."""

    key: str
    label: str
    focus: str
    confidence: Literal["strong", "likely", "general"]
    matched: tuple[str, ...]


def _singular(word: str) -> str:
    plural = len(word) > 3 and word.endswith("s") and word[-2:] not in _NOT_PLURAL
    return word[:-1] if plural else word


def _domain(key: str, label: str, focus: str, keywords: str, measures: str) -> Domain:
    return Domain(
        key,
        label,
        focus,
        frozenset(_singular(word) for word in keywords.split()),
        tuple(_singular(word) for word in measures.split()),
    )


GENERAL = _domain(
    "general",
    "General data",
    "Overview of this table",
    "",
    "revenue sale amount price cost total value",
)

DOMAINS = (
    _domain(
        "retail",
        "Retail and sales",
        "Revenue, orders and what drives them",
        "order customer product sku sale revenue discount quantity qty cart store "
        "basket shipped merchant brand",
        "revenue sale amount profit quantity qty price discount",
    ),
    _domain(
        "finance",
        "Finance and banking",
        "Money movement, balances and exposure",
        "transaction account balance debit credit loan interest invoice payment "
        "expense budget portfolio asset liability equity ledger tax",
        "amount balance payment expense revenue interest",
    ),
    _domain(
        "healthcare",
        "Healthcare",
        "Patients, treatments and outcomes",
        "patient diagnosis hospital doctor physician treatment medication drug dose "
        "admission discharge blood bmi disease clinical symptom mortality nurse ward",
        "cost charge stay dose bmi age",
    ),
    _domain(
        "people",
        "People and HR",
        "Workforce, pay and retention",
        "employee salary department hire attrition tenure manager bonus payroll "
        "headcount staff overtime",
        "salary bonus tenure overtime",
    ),
    _domain(
        "marketing",
        "Marketing",
        "Campaign reach, spend and conversion",
        "campaign click impression ctr conversion lead channel spend audience "
        "subscriber bounce contact",
        "spend conversion click impression revenue",
    ),
    _domain(
        "logistics",
        "Logistics and transport",
        "Trips, shipments and delivery performance",
        "shipment carrier warehouse freight delivery route tracking vehicle transit "
        "pickup dropoff fare trip driver passenger toll",
        "fare cost distance weight duration tip",
    ),
    _domain(
        "education",
        "Education",
        "Learners, courses and results",
        "student course grade teacher school enrolment enrollment exam cohort "
        "learner gpa attendance semester",
        "score grade gpa attendance",
    ),
    _domain(
        "energy",
        "Energy and utilities",
        "Generation, consumption and meter readings",
        "kwh mwh energy meter voltage generation consumption solar turbine grid "
        "utility sensor reading",
        "kwh mwh generation consumption voltage",
    ),
    _domain(
        "manufacturing",
        "Manufacturing",
        "Output, quality and downtime",
        "defect machine production batch inspection yield plant downtime assembly "
        "scrap factory",
        "output yield defect scrap downtime",
    ),
    _domain(
        "property",
        "Real estate",
        "Prices, rents and property features",
        "property bedroom bathroom sqft rent listing mortgage zoning tenant landlord",
        "price rent sqft",
    ),
    _domain(
        "environment",
        "Weather and environment",
        "Conditions, emissions and change over time",
        "temperature temp precipitation rainfall humidity emission climate "
        "weather pollution aqi",
        "precipitation temp temperature emission humidity",
    ),
    _domain(
        "public",
        "Population and economy",
        "People, income and regional comparison",
        "population country census household income unemployment gdp birth death "
        "state county",
        "population income gdp unemployment death",
    ),
    _domain(
        "sports",
        "Sports",
        "Teams, players and results",
        "team player match goal season league opponent innings",
        "goal point score",
    ),
)


def name_tokens(name: str) -> list[str]:
    """Split a name into lower-case singular words, including camelCase."""
    return [_singular(word.casefold()) for word in _TOKEN.findall(name)]


def detect_domain(names: Iterable[str]) -> tuple[Domain, DomainMatch]:
    """Choose the area with the most distinct matching words.

    A single matching word, or a tie for first place, stays ``general``:
    guessing a domain from thin evidence would mislead more than it helps.
    """
    tokens = {token for name in names for token in name_tokens(name)}
    ranked = sorted(
        ((sorted(tokens & domain.keywords), domain) for domain in DOMAINS),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    matched, domain = ranked[0]
    runner_up = len(ranked[1][0])
    if len(matched) < _MIN_MATCHES or len(matched) == runner_up:
        return GENERAL, DomainMatch(
            GENERAL.key, GENERAL.label, GENERAL.focus, "general", ()
        )
    confidence: Literal["strong", "likely"] = (
        "strong"
        if len(matched) >= _STRONG_MATCHES and len(matched) >= 2 * runner_up
        else "likely"
    )
    return domain, DomainMatch(
        domain.key, domain.label, domain.focus, confidence, tuple(matched)
    )
