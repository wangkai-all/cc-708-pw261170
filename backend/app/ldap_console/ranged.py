"""Range retrieval: demo-service segmentation and receiver-side assembly.

LDAP range retrieval (the ``;range=low-high`` attribute option, as used by
Active Directory and emulated here by the demo service) lets a server return
a large multi-valued attribute in several *segments*. Each segment carries a
result tag saying which indices it contains:

* request  ``member;range=0-2``   -> response ``member;range=0-2``   (more)
* request  ``member;range=3-*``   -> response ``member;range=3-9``   (last)

The final segment carries a **concrete** upper bound; while more data exists
the server keeps ``*`` as the upper bound of the returned tag.

This module has two sides:

* :class:`DemoRangeService` — segments a value list for the demo directory.
  Range retrieval is a *service-specific* contract: nothing here assumes every
  LDAP server supports it, and the assembler also tolerates servers that
  simply return the whole attribute with no range tag.
* :class:`RangeAssembler` — the receiver: issues tagged requests through a
  supplied fetcher, stitches the segments together, and records every segment
  so the UI can inspect missing indices, overlaps and stalled boundaries. An
  injected fault (gap / overlap / stall) is detected rather than looped on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from .config import settings

# A raw segment as returned by a service: attribute tag, ordered raw values.
RawSegment = tuple[str, list[bytes]]


@dataclass(frozen=True)
class RangeTag:
    low: int
    high: int | None  # None means '*' (server promises more)

    @property
    def is_open_ended(self) -> bool:
        return self.high is None

    def request_option(self) -> str:
        high = "*" if self.high is None else str(self.high)
        return f"range={self.low}-{high}"

    @classmethod
    def parse(cls, tag: str) -> "RangeTag":
        # tag looks like "member;range=0-2" or "member;range=3-*"
        marker = "range="
        idx = tag.lower().find(marker)
        if idx < 0:
            raise ValueError(f"not a range tag: {tag!r}")
        low_high = tag[idx + len(marker):]
        low_text, _, high_text = low_high.partition("-")
        low = int(low_text)
        high = None if high_text == "*" else int(high_text)
        return RangeTag(low=low, high=high)


@dataclass(frozen=True)
class SegmentRecord:
    """One received segment, kept for UI inspection and fault diagnosis."""

    request_tag: str
    response_tag: str
    low: int
    high: int | None
    count: int
    expected_next_low: int
    values: list[bytes] = field(repr=False)


@dataclass(frozen=True)
class RangeFault:
    kind: str  # gap | overlap | stall | invalid-tag | empty-nonterminal
    detail: str
    segment_index: int


@dataclass
class RangeResult:
    attribute: str
    complete: bool
    values: list[bytes] = field(default_factory=list)
    segments: list[SegmentRecord] = field(default_factory=list)
    faults: list[RangeFault] = field(default_factory=list)
    reason: str | None = None

    @property
    def covered_indices(self) -> tuple[int, int] | None:
        """Inclusive index span actually covered, ignoring overlaps."""
        if not self.segments:
            return None
        lows = [s.low for s in self.segments]
        concrete_highs = [s.high for s in self.segments if s.high is not None]
        if not concrete_highs:
            return min(lows), None  # type: ignore[return-value]
        return min(lows), max(concrete_highs)


# --------------------------------------------------------------------------- #
# Service side (demo directory only)
# --------------------------------------------------------------------------- #


class DemoRangeService:
    """Segments value lists using the demo service's range convention."""

    def __init__(self, page_size: int | None = None,
                 threshold: int | None = None) -> None:
        self.page_size = page_size or settings.range_page_size
        self.threshold = threshold or settings.range_threshold

    def should_segment(self, attribute: str, value_count: int) -> bool:
        return (
            attribute.lower() in settings.ranged_attributes
            and value_count > self.threshold
        )

    def serve(self, attribute: str, values: list[bytes],
              requested_option: str | None) -> RawSegment | None:
        """Return the tagged segment for one requested range option.

        ``requested_option`` is the full ``attr;range=...`` request tag or
        ``None`` for a plain attribute request. Returns ``None`` when the
        attribute is not segmented by this service.
        """
        if not self.should_segment(attribute, len(values)):
            return None

        total = len(values)
        if requested_option is None:
            # Plain request over the threshold: the server starts the range
            # conversation itself (AD behaviour).
            low, high = 0, min(self.page_size - 1, total - 1)
        else:
            tag = RangeTag.parse(requested_option)
            low = tag.low
            if tag.high is None:  # range=N-* : "to end"
                high = min(low + self.page_size - 1, total - 1)
            else:
                high = min(tag.high, total - 1)

        if low >= total:
            return f"{attribute};range={low}-*", []
        chunk = values[low:high + 1]
        returned_high = high if high >= total - 1 else None
        response_high = str(returned_high) if returned_high is not None else "*"
        return f"{attribute};range={low}-{response_high}", chunk


# --------------------------------------------------------------------------- #
# Receiver side
# --------------------------------------------------------------------------- #

# Fetcher protocol: given the full request attribute name (e.g.
# "member;range=3-*") return the service's RawSegment, or None when the
# service does not know the attribute.
SegmentFetcher = Callable[[str], "RawSegment | None"]


class RangeAssembler:
    """Assembles a multi-segment attribute and diagnoses range faults.

    The assembler is transport-agnostic: it never imports ldap3 or FastAPI.
    A ``fetcher`` callable performs the actual (possibly remote) lookup, which
    makes the fault-injection and unit tests straightforward.
    """

    MAX_ITERATIONS = 10_000

    def __init__(self, fetcher: SegmentFetcher) -> None:
        self._fetcher = fetcher

    def fetch(self, attribute: str) -> RangeResult:
        result = RangeResult(attribute=attribute, complete=False)

        # First round: ask plainly. A server without range support will just
        # hand back the complete attribute (no ';range=' in the response tag).
        first = self._fetcher(attribute)
        if first is None:
            result.reason = "attribute absent"
            return result

        response_tag, chunk = first
        if "range=" not in response_tag.lower():
            # Non-segmented service: full attribute in one response.
            result.values.extend(chunk)
            result.segments.append(
                SegmentRecord(
                    request_tag=attribute,
                    response_tag=attribute,
                    low=0,
                    high=len(chunk) - 1 if chunk else None,
                    count=len(chunk),
                    expected_next_low=len(chunk),
                    values=list(chunk),
                )
            )
            result.complete = True
            return result

        self._consume_segment(result, attribute, response_tag, chunk)

        iteration = 0
        while not result.complete and not result.faults and iteration < self.MAX_ITERATIONS:
            iteration += 1
            last = result.segments[-1]
            # An open-ended segment (high='*') promises more data; the next
            # request begins right after the values actually delivered.
            if last.high is None:
                next_low = last.low + last.count
            else:
                next_low = last.high + 1
            request_tag = f"{attribute};range={next_low}-*"
            response = self._fetcher(request_tag)
            if response is None:
                result.faults.append(
                    RangeFault(
                        "gap",
                        f"service returned no segment for {request_tag}; "
                        f"indices from {next_low} are missing",
                        len(result.segments),
                    )
                )
                break
            response_tag, chunk = response
            self._consume_segment(result, request_tag, response_tag, chunk)

        if iteration >= self.MAX_ITERATIONS and not result.complete:
            result.faults.append(
                RangeFault("stall", "iteration limit reached without a terminal segment",
                           len(result.segments))
            )
        return result

    def _consume_segment(self, result: RangeResult, request_tag: str,
                         response_tag: str, chunk: list[bytes]) -> None:
        try:
            tag = RangeTag.parse(response_tag)
        except ValueError as exc:
            result.faults.append(
                RangeFault("invalid-tag", str(exc), len(result.segments))
            )
            return

        previous: SegmentRecord | None = result.segments[-1] if result.segments else None
        if previous is not None:
            # For an open-ended previous segment the next expected index is
            # derived from the values actually delivered, not its high bound.
            if previous.high is None:
                expected_low = previous.low + previous.count
            else:
                expected_low = previous.high + 1
            if tag.low < expected_low:
                result.faults.append(
                    RangeFault(
                        "overlap",
                        f"segment starts at {tag.low} but next expected index "
                        f"was {expected_low}",
                        len(result.segments),
                    )
                )
            elif tag.low > expected_low:
                result.faults.append(
                    RangeFault(
                        "gap",
                        f"indices {expected_low}..{tag.low - 1} missing "
                        f"(segment starts at {tag.low})",
                        len(result.segments),
                    )
                )

        if not chunk and tag.high is None:
            # Empty open-ended segment: boundary cannot progress -> stall.
            result.faults.append(
                RangeFault(
                    "stall",
                    f"empty segment at low={tag.low} with no concrete upper bound",
                    len(result.segments),
                )
            )
            result.segments.append(
                SegmentRecord(request_tag, response_tag, tag.low, tag.high, 0,
                              tag.low, [])
            )
            return

        result.values.extend(chunk)
        expected_next = tag.low + len(chunk)
        result.segments.append(
            SegmentRecord(
                request_tag=request_tag,
                response_tag=response_tag,
                low=tag.low,
                high=tag.high,
                count=len(chunk),
                expected_next_low=expected_next,
                values=list(chunk),
            )
        )
        # A concrete high bound marks the terminal segment.
        if tag.high is not None:
            result.complete = True


def describe_coverage(segments: Iterable[SegmentRecord]) -> dict[str, object]:
    """Summarize received segments for the web UI's inspection view."""
    segs = list(segments)
    if not segs:
        return {"segments": 0}
    covered: set[int] = set()
    delivered_spans: list[tuple[int, int]] = []
    for seg in segs:
        # Open-ended segments still delivered `count` concrete values, whose
        # indices are low .. low+count-1 regardless of the '*' high bound.
        if seg.count:
            span = (seg.low, seg.low + seg.count - 1)
            delivered_spans.append(span)
            covered.update(range(span[0], span[1] + 1))
    max_high = max((end for _, end in delivered_spans), default=None)
    missing = (
        sorted(set(range(0, max_high + 1)) - covered)
        if max_high is not None
        else []
    )
    return {
        "segments": len(segs),
        "first_index": segs[0].low,
        "last_index": max_high,
        "missing_indices": missing,
        "total_values": sum(s.count for s in segs),
    }
