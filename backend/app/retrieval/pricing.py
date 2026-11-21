"""The one net-price rule for a student (Stage B filter, Stage C score, facts, claims).

Scorecard's public-school net price (``NPT4x_PUB``) is computed for students paying
**in-state** tuition. An out-of-state student at a public school pays the out-of-state
sticker surcharge on top, which aid rarely covers, so we estimate:

====================================  =======================================  ====================
school                                value                                    basis
====================================  =======================================  ====================
private nonprofit / for-profit        bracket net price                        ``private``
public, school state == home state    bracket net price                        ``in_state``
public, home state unknown            bracket net price (published figure)     ``in_state``
public, school state != home state    bracket price + (TUITIONFEE_OUT - _IN)   ``est_out_of_state``
public out-of-state, tuition missing  None                                     ``unknown``
bracket net price missing             None                                     ``unknown``
====================================  =======================================  ====================

The surcharge is floored at 0 (a handful of publics report equal fees). The bracket
column comes from :func:`net_price_column` (average net price when the bracket is
unknown). ``fallback_to_avg=True`` (filter/scoring only) uses the school's average net
price when the bracket figure is missing, before applying the same rule; what the
student is shown (``facts["net_price"]``) and what claims are checked against never
use that fallback.
"""

from __future__ import annotations

from typing import Any

from app.schemas import NetPriceBasis

__all__ = ["NET_PRICE_COLUMNS", "NetPriceBasis", "net_price_column", "student_net_price"]

CONTROL_PUBLIC = 1

NET_PRICE_COLUMNS: dict[str, str] = {
    "0-30k": "net_price_0_30k",
    "30-48k": "net_price_30_48k",
    "48-75k": "net_price_48_75k",
    "75-110k": "net_price_75_110k",
    "110k+": "net_price_110k_plus",
}


def net_price_column(bracket: str | None) -> str:
    """Institution column holding the (published) net price for ``bracket``."""
    if bracket is None:
        return "avg_net_price"
    return NET_PRICE_COLUMNS[bracket]


def student_net_price(
    row: Any,
    bracket: str | None,
    home_state: str | None,
    *,
    fallback_to_avg: bool = False,
) -> tuple[int | None, NetPriceBasis]:
    """Net price this student would pay at ``row`` and how it was derived.

    ``row`` is anything with the institution columns as attributes (``Institution``,
    ``CandidateRow``): ``control``, ``state``, the ``net_price_*`` columns,
    ``avg_net_price``, ``tuition_in_state``, ``tuition_out_of_state``.
    """
    base: int | None = getattr(row, net_price_column(bracket))
    if base is None and fallback_to_avg:
        base = row.avg_net_price
    if base is None:
        return None, "unknown"
    if row.control != CONTROL_PUBLIC:
        return int(base), "private"
    home = (home_state or "").strip().upper()
    if not home or home == (row.state or "").upper():
        return int(base), "in_state"
    t_in, t_out = row.tuition_in_state, row.tuition_out_of_state
    if t_in is None or t_out is None:
        return None, "unknown"
    return int(base) + max(int(t_out) - int(t_in), 0), "est_out_of_state"
