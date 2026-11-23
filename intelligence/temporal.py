"""
Intelligence Layer — Temporal Query Decomposition

Extracts temporal constraints from natural-language queries, mapping them
into naive ISO timestamps for time-filtered retrieval, and produces a residual
semantic query for content ranking.

Zero LLM calls, zero heavy dependencies — fast, deterministic, reproducible.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, time as dtime, timedelta
from typing import Optional, List, Tuple
import re

from config import AROUND_WINDOW_MINUTES


@dataclass
class TemporalParse:
    start: Optional[str] = None          # Naive local ISO: "YYYY-MM-DDTHH:MM:SS"
    end: Optional[str] = None            # Naive local ISO: "YYYY-MM-DDTHH:MM:SS"
    residual_query: str = ""             # Semantic query with temporal spans and filler removed
    intent: str = "search"               # "apps", "duration", "latest", "earliest", or "search"
    is_future: bool = False              # True if time expression refers to future
    matched_spans: List[str] = field(default_factory=list)


# Month name mapping
MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "a couple": 2, "a couple of": 2, "a": 1,
}

FUTURE_PATTERNS = [
    r"\btomorrow\b",
    r"\bnext\s+(?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\bin\s+the\s+future\b",
    r"\bupcoming\b",
    r"\blater\s+today\b",
]

FILLER_PATTERNS = [
    r"\bwhat\s+was\s+i\s+doing\b",
    r"\bwhat\s+did\s+i\s+do\b",
    r"\bwhat\s+was\s+on\s+my\s+screen\b",
    r"\bwhat\s+apps\s+did\s+i\s+use\b",
    r"\bwhich\s+apps\s+did\s+i\s+use\b",
    r"\bhow\s+long\s+did\s+i\s+spend\s+on\b",
    r"\bhow\s+long\s+did\s+i\s+spend\b",
    r"\bwhat\s+was\s+the\s+last\s+thing\s+i\s+was\s+doing\b",
    r"\bwhat\s+was\s+the\s+last\s+thing\b",
    r"\bwhen\s+did\s+i\s+start\s+working\b",
    r"\bwhen\s+did\s+i\s+start\b",
    r"\bfind\s+captures\s+where\b",
    r"\bwhere\s+did\s+i\s+see\s+the\s+word\b",
    r"\bwhere\s+did\s+i\s+see\b",
    r"\bfind\s+where\s+i\s+was\s+looking\s+at\b",
    r"\bfind\s+where\s+i\s+was\b",
    r"\bwhich\s+files\s+was\s+i\s+editing\s+in\b",
    r"\bwhich\s+files\s+was\s+i\s+editing\b",
    r"\bwhat\s+websites\s+was\s+i\s+visiting\s+on\b",
    r"\bwhat\s+websites\s+was\s+i\s+visiting\b",
    r"\bwhat\s+was\s+i\s+reading\s+about\b",
    r"\bwhat\s+was\s+i\s+reading\b",
    r"\bwas\s+i\s+reading\b",
    r"\bwhat\s+was\s+i\s+working\s+on\s+in\b",
    r"\bwhat\s+was\s+i\s+working\s+on\b",
    r"\bwas\s+i\s+working\s+on\b",
    r"\bsummarize\s+what\s+i\s+did\s+with\b",
    r"\bsummarize\s+what\s+i\s+did\s+on\b",
    r"\bsummarize\s+what\s+i\s+did\b",
    r"\bdid\s+i\s+look\s+at\b",
    r"\bdid\s+i\s+finish\b",
    r"\bwas\s+i\s+having\s+in\b",
    r"\bwas\s+i\s+having\b",
    r"\bdid\s+i\s+perform\s+in\b",
    r"\bdid\s+i\s+perform\b",
    r"\bwas\s+open\s+in\s+the\s+editor\b",
    r"\bwas\s+open\s+in\s+editor\b",
    r"\bwas\s+open\s+in\b",
    r"\bwas\s+open\b",
    r"\bopen\s+in\s+the\s+editor\b",
    r"\bopen\s+in\s+editor\b",
    r"\bwhat\s+did\s+my\s+colleague\s+say\s+about\b",
]


def _parse_clock_time(time_str: str) -> Optional[dtime]:
    """Parse clock times like 3pm, 3:15 PM, 15:15, 950 PM, 1000 PM."""
    clean = time_str.strip().lower()

    # Colon-less with am/pm: 950 pm, 1000 pm, 415 pm
    m_colonless = re.match(r"^(\d{1,2})(\d{2})\s*(am|pm)$", clean)
    if m_colonless:
        hr = int(m_colonless.group(1))
        mn = int(m_colonless.group(2))
        meridiem = m_colonless.group(3)
        if meridiem == "pm" and hr < 12:
            hr += 12
        elif meridiem == "am" and hr == 12:
            hr = 0
        if 0 <= hr <= 23 and 0 <= mn <= 59:
            return dtime(hr, mn)

    # Standard H:MM or H:MM:SS with optional am/pm
    m_standard = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?$", clean)
    if m_standard:
        hr = int(m_standard.group(1))
        mn = int(m_standard.group(2))
        sc = int(m_standard.group(3)) if m_standard.group(3) else 0
        meridiem = m_standard.group(4)
        if meridiem == "pm" and hr < 12:
            hr += 12
        elif meridiem == "am" and hr == 12:
            hr = 0
        if 0 <= hr <= 23 and 0 <= mn <= 59:
            return dtime(hr, mn, sc)

    # Simple H am/pm, e.g. 3pm, 4 pm
    m_simple = re.match(r"^(\d{1,2})\s*(am|pm)$", clean)
    if m_simple:
        hr = int(m_simple.group(1))
        meridiem = m_simple.group(2)
        if meridiem == "pm" and hr < 12:
            hr += 12
        elif meridiem == "am" and hr == 12:
            hr = 0
        if 0 <= hr <= 23:
            return dtime(hr, 0, 0)

    # 24-hour H:MM
    m_24h = re.match(r"^(\d{1,2}):(\d{2})$", clean)
    if m_24h:
        hr = int(m_24h.group(1))
        mn = int(m_24h.group(2))
        if 0 <= hr <= 23 and 0 <= mn <= 59:
            return dtime(hr, mn, 0)

    return None


def parse_temporal(query: str, now: datetime) -> TemporalParse:
    """
    Parse temporal constraints from a natural-language query relative to a reference 'now'.

    Args:
        query: User's question or search query.
        now: Reference datetime (mandatory for reproducible evaluation).

    Returns:
        TemporalParse with start, end, residual_query, intent, and is_future.
    """
    if not isinstance(now, datetime):
        raise TypeError(f"'now' must be a datetime instance, got {type(now)}")

    result = TemporalParse()
    q = query
    matched_spans = []

    # 1. Intent Detection
    q_lower = q.lower()
    if re.search(r"\b(what|which)\s+(apps|applications)\b", q_lower):
        result.intent = "apps"
    elif re.search(r"\b(how\s+long|how\s+much\s+time|time\s+spent)\b", q_lower):
        result.intent = "duration"
    elif re.search(r"\b(last\s+thing|latest\s+thing|last\s+activity)\b", q_lower):
        result.intent = "latest"
    elif re.search(r"\b(when\s+did\s+i\s+start|first\s+thing|earliest)\b", q_lower):
        result.intent = "earliest"
    else:
        result.intent = "search"

    # 2. Future Detection
    for fut_pat in FUTURE_PATTERNS:
        m = re.search(fut_pat, q, re.IGNORECASE)
        if m:
            result.is_future = True
            matched_spans.append(m.group(0))

    # Check for future times explicitly (e.g. tomorrow morning at 10 AM)
    if re.search(r"\btomorrow\s+morning\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", q, re.IGNORECASE):
        result.is_future = True
        matched_spans.append(re.search(r"\btomorrow\s+morning\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", q, re.IGNORECASE).group(0))

    # 3. Explicit Date Parsing (e.g., "November 23", "September 5th", "August 15th")
    target_date: Optional[date] = None

    date_pattern = (
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?\b"
    )
    m_date = re.search(date_pattern, q, re.IGNORECASE)
    if m_date:
        matched_spans.append(m_date.group(0))
        m_name = m_date.group(1).lower()
        month = MONTH_MAP.get(m_name, 1)
        day = int(m_date.group(2))
        year = int(m_date.group(3)) if m_date.group(3) else None

        if year is None:
            # Resolves to most recent past occurrence relative to now
            candidate_year = now.year
            try:
                candidate_date = date(candidate_year, month, day)
                if candidate_date > now.date():
                    year = candidate_year - 1
                else:
                    year = candidate_year
            except ValueError:
                year = candidate_year
        try:
            target_date = date(year, month, day)
            if target_date > now.date():
                result.is_future = True
        except ValueError:
            target_date = None

    # Check relative dates if no explicit date
    if not target_date:
        if re.search(r"\btoday\b", q, re.IGNORECASE):
            m = re.search(r"\btoday\b", q, re.IGNORECASE)
            matched_spans.append(m.group(0))
            target_date = now.date()
        elif re.search(r"\byesterday\b", q, re.IGNORECASE):
            m = re.search(r"\byesterday\b", q, re.IGNORECASE)
            matched_spans.append(m.group(0))
            target_date = now.date() - timedelta(days=1)
        elif re.search(r"\blast\s+night\b", q, re.IGNORECASE):
            m = re.search(r"\blast\s+night\b", q, re.IGNORECASE)
            matched_spans.append(m.group(0))
            # Last night: from previous day 21:00 to current day 05:00
            prev_day = now.date() - timedelta(days=1)
            result.start = datetime.combine(prev_day, dtime(21, 0, 0)).isoformat()
            result.end = datetime.combine(now.date(), dtime(5, 0, 0)).isoformat()

    # Check relative offsets like "three months ago", "2 hours ago"
    offset_pat = r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|a couple)\s+(minutes?|hours?|days?|weeks?|months?)\s+ago\b"
    m_offset = re.search(offset_pat, q, re.IGNORECASE)
    if m_offset:
        matched_spans.append(m_offset.group(0))
        num_str = m_offset.group(1).lower()
        unit = m_offset.group(2).lower()
        val = int(num_str) if num_str.isdigit() else NUMBER_WORDS.get(num_str, 1)

        if "month" in unit:
            # e.g., three months ago -> roughly 90 days or month subtraction
            calc_year = now.year
            calc_month = now.month - val
            while calc_month <= 0:
                calc_month += 12
                calc_year -= 1
            calc_day = min(now.day, 28)
            offset_date = date(calc_year, calc_month, calc_day)
            if not target_date:
                target_date = offset_date
        elif "day" in unit:
            offset_date = now.date() - timedelta(days=val)
            if not target_date:
                target_date = offset_date
        elif "hour" in unit:
            anchor_dt = now - timedelta(hours=val)
            if not result.start and not result.end:
                result.start = (anchor_dt - timedelta(minutes=AROUND_WINDOW_MINUTES)).isoformat()
                result.end = (anchor_dt + timedelta(minutes=AROUND_WINDOW_MINUTES)).isoformat()

    # 4. Day-part Expressions
    # Day-parts: morning 05–12, afternoon 12–17, evening 17–21, night 21–05
    day_part: Optional[Tuple[dtime, dtime]] = None
    day_part_pat = r"\b(this\s+morning|this\s+afternoon|this\s+evening|morning|afternoon|evening|night|after\s+lunch)\b"
    m_dp = re.search(day_part_pat, q, re.IGNORECASE)
    if m_dp and not result.start:
        dp_text = m_dp.group(1).lower()
        matched_spans.append(m_dp.group(0))
        if "morning" in dp_text:
            day_part = (dtime(5, 0, 0), dtime(12, 0, 0))
        elif "afternoon" in dp_text or "after lunch" in dp_text:
            day_part = (dtime(12, 0, 0), dtime(17, 0, 0))
        elif "evening" in dp_text:
            day_part = (dtime(17, 0, 0), dtime(21, 0, 0))
        elif "night" in dp_text:
            day_part = (dtime(21, 0, 0), dtime(23, 59, 59))

        if not target_date:
            target_date = now.date()

    # 5. Clock Time Expressions
    # 5a. "between X and Y"
    # Matches patterns like: between 9:40 PM and 10:00 PM, between 4pm and 5pm, between 413 PM and 418 PM
    time_token = r"\d{1,2}(?::\d{2})?(?:\d{2})?\s*(?:am|pm)?|\d{1,2}:\d{2}"
    between_pat = rf"\bbetween\s+({time_token})\s+and\s+({time_token})\b"
    m_between = re.search(between_pat, q, re.IGNORECASE)

    if m_between:
        matched_spans.append(m_between.group(0))
        t1_raw = m_between.group(1)
        t2_raw = m_between.group(2)

        # Contextual meridiem inheritance (e.g. "between 2 and 4pm" -> 2pm and 4pm)
        if ("pm" in t2_raw.lower() or "am" in t2_raw.lower()) and not ("pm" in t1_raw.lower() or "am" in t1_raw.lower()):
            meridiem = "pm" if "pm" in t2_raw.lower() else "am"
            t1_raw = f"{t1_raw.strip()} {meridiem}"

        t1 = _parse_clock_time(t1_raw)
        t2 = _parse_clock_time(t2_raw)

        if t1 and t2:
            d = target_date or now.date()
            result.start = datetime.combine(d, t1).isoformat()
            result.end = datetime.combine(d, t2).isoformat()

    # 5b. "around X" or "at X"
    if not result.start:
        around_pat = rf"\b(around|at|about)\s+({time_token})\b"
        m_around = re.search(around_pat, q, re.IGNORECASE)
        if m_around:
            matched_spans.append(m_around.group(0))
            t_raw = m_around.group(2)
            t = _parse_clock_time(t_raw)
            if t:
                # If no date was found, resolve to the most recent past occurrence of that time
                d = target_date
                if not d:
                    cand_dt = datetime.combine(now.date(), t)
                    if cand_dt > now:
                        d = now.date() - timedelta(days=1)
                    else:
                        d = now.date()
                center_dt = datetime.combine(d, t)
                result.start = (center_dt - timedelta(minutes=AROUND_WINDOW_MINUTES)).isoformat()
                result.end = (center_dt + timedelta(minutes=AROUND_WINDOW_MINUTES)).isoformat()

    # 5c. Standalone clock time if not already matched
    if not result.start and not day_part:
        standalone_pat = rf"\b({time_token})\b"
        # Only check if contains am/pm or colon to avoid false matching standalone numbers
        for m_st in re.finditer(standalone_pat, q, re.IGNORECASE):
            token = m_st.group(1)
            if any(indicator in token.lower() for indicator in ["am", "pm", ":"]):
                t = _parse_clock_time(token)
                if t:
                    matched_spans.append(m_st.group(0))
                    d = target_date or now.date()
                    center_dt = datetime.combine(d, t)
                    result.start = (center_dt - timedelta(minutes=AROUND_WINDOW_MINUTES)).isoformat()
                    result.end = (center_dt + timedelta(minutes=AROUND_WINDOW_MINUTES)).isoformat()
                    break

    # If day-part was detected and no clock time was specified:
    if day_part and not result.start:
        d = target_date or now.date()
        result.start = datetime.combine(d, day_part[0]).isoformat()
        end_cand = datetime.combine(d, day_part[1])
        if d == now.date() and end_cand > now:
            result.end = now.isoformat()
        else:
            result.end = end_cand.isoformat()

    # If date was specified but no clock time or day-part:
    if target_date and not result.start:
        result.start = datetime.combine(target_date, dtime(0, 0, 0)).isoformat()
        end_cand = datetime.combine(target_date, dtime(23, 59, 59))
        if target_date == now.date() and end_cand > now:
            result.end = now.isoformat()
        else:
            result.end = end_cand.isoformat()

    # 6. Residual Query Extraction
    residual = q
    # Remove matched temporal spans
    for span in matched_spans:
        residual = re.sub(re.escape(span), " ", residual, flags=re.IGNORECASE)

    # Remove query template / filler phrases
    for f_pat in FILLER_PATTERNS:
        residual = re.sub(f_pat, " ", residual, flags=re.IGNORECASE)

    # Remove lingering temporal prepositions/connectors
    residual = re.sub(r"\b(around|between|and|at|on|in|during|from|to|when|what|did|was|i|were|the|of)\b", " ", residual, flags=re.IGNORECASE)

    # Remove punctuation
    residual = re.sub(r"[?!\"',;:]", " ", residual)
    residual = re.sub(r"\s+", " ", residual).strip()

    result.residual_query = residual
    result.matched_spans = matched_spans

    return result
