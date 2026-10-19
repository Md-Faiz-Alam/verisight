"""Context-local generation metadata, with no prompts, responses or credentials."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

GenerationStage = Literal["investigator", "structured_synthesis", "text_generation"]


@dataclass(frozen=True, slots=True)
class GenerationCallReport:
    stage: GenerationStage
    call_number: int
    attempts: int
    elapsed_seconds: float
    returned_text: bool


@dataclass(slots=True)
class GenerationCall:
    stage: GenerationStage
    call_number: int
    attempts: int = 0
    returned_text: bool = False


_active_calls: ContextVar[list[GenerationCallReport] | None] = ContextVar(
    "verisight_generation_calls", default=None
)


@contextmanager
def capture_generation_calls() -> Iterator[list[GenerationCallReport]]:
    """Capture calls in this context; restore the preceding scope on exit."""
    calls: list[GenerationCallReport] = []
    token = _active_calls.set(calls)
    try:
        yield calls
    finally:
        _active_calls.reset(token)


@contextmanager
def track_generation_call(
    stage: GenerationStage, call_number: int
) -> Iterator[GenerationCall]:
    """Measure a whole generation call, including its retry delays and attempts."""
    call = GenerationCall(stage=stage, call_number=call_number)
    started = perf_counter()
    try:
        yield call
    finally:
        calls = _active_calls.get()
        if calls is not None:
            calls.append(
                GenerationCallReport(
                    stage=call.stage,
                    call_number=call.call_number,
                    attempts=call.attempts,
                    elapsed_seconds=round(perf_counter() - started, 3),
                    returned_text=call.returned_text,
                )
            )
