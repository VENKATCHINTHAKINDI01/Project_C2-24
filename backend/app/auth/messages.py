"""What an officer is told when something is not available to them (ADR-0016; plan §5.4, §5.9).

One message for a record that does not exist AND one the officer may not see: the words, status
code and body never differ, so nothing about existence is revealed (CLAUDE.md §4.7). The message
still guides: if the officer needs it for their work, the route to it is the competent authority
through e-Office — never C2-24.
"""

from __future__ import annotations

GUIDE = (
    "If you need it for your work, please request access or approval from the competent "
    "authority through e-Office (your section / controlling officer)."
)

# A cited order C2-24 does not hold reads exactly like one the officer may not see (ADR-0019,
# owner choice 12 Nov 2026): one honest sentence that covers both, never "does not exist".
NOT_IN_COLLECTION = "It may not be in C2-24's collection yet, or you may need access."
CITED_NOT_FOUND = f"Not found in the records available to you. {NOT_IN_COLLECTION} {GUIDE}"

FILE_NOT_AVAILABLE = f"This file isn't available to you. {GUIDE}"
DOCUMENT_NOT_AVAILABLE = f"This document isn't available to you. {NOT_IN_COLLECTION} {GUIDE}"
RECEIPT_NOT_AVAILABLE = f"This receipt isn't available to you. {GUIDE}"
REVIEW_ITEM_NOT_AVAILABLE = f"This review item isn't available to you. {GUIDE}"

# Anything that failed inside (a store timed out, an engine broke): the same words every time,
# with nothing about the cause (CLAUDE.md §4.4)
NEUTRAL_FAILURE = "The request could not be completed right now. Please try again later."
