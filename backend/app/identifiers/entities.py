"""Entity resolution: people and offices named in the records (Tier 2; ADR-0058; plan §1 Tier 2).

Deterministic and conservative, like canonical-ID resolution (CLAUDE.md §5.6: never guess):

- an OFFICER who signed notes is identified by the e-Office officer ID the source system records
  for the paper (`SourceArtefact.signers`), not by the name text: two officers with the same
  name and initials are two entities (owner, 18 Nov 2026: "we have officer IDs; differentiate by
  the ID and the name"). The name is only how a question finds them;
- any other PERSON is a name written with initials ("Sri K. Venkata Ramana", "Ch. Suresh Babu") or
  a noting signature with no officer ID (older PDF notings). Its key is its initials and name
  words, so "Sri K. Venkata Ramana", "K.Venkata Ramana" and "Sri K Venkata Ramana" are one person;
  "K." and "M." Venkata Ramana are two. A name asked WITHOUT initials matches every person and
  officer with those name words, each reported separately — never merged by guess;
- an OFFICE is a field office named with its station ("Regional Office, Tirupati").

The index is built from trusted (indexed) text only, and it is NOT an access boundary: callers ask
it which records name an entity and then keep only the records the officer may see
(`visible_document`), so a person or office named only in records outside the scope is never
found, named or counted — the answer is the same as for a name that appears nowhere.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from app.connectors.eoffice import Signer


class EntityKind(StrEnum):
    PERSON = "person"
    OFFICER = "officer"  # identified by an e-Office officer ID
    OFFICE = "office"


@dataclass(frozen=True)
class Mention:
    kind: EntityKind
    key: str  # the entity it resolves to
    surface: str  # as written (or, for an officer, the name e-Office records)
    role: str = ""  # designation / office written next to it in THIS record (may differ by record)
    signed: bool = False  # a noting signature: the person wrote / forwarded this record
    name_key: str = ""  # initials|name words, how a question finds it (people and officers)


_HONORIFIC = r"(?:Sri|Shri|Smt\.?|Kum\.?|Dr\.?|Thiru|Selvi)"
_INI = r"(?:[A-Z][a-z]?\.\s?){1,4}"  # "K.", "K. V.", "Ch."
_NAME = r"[A-Z][a-z]{2,}(?: [A-Z][a-z]{2,}){0,3}"  # one line: a name never spans a break
PERSON = re.compile(rf"\b{_HONORIFIC}\s+(?P<ini>{_INI}|(?:[A-Z]\s){{1,4}})?\s*(?P<name>{_NAME})")
INITIALLED = re.compile(rf"(?<![\w.])(?P<ini>{_INI})\s*(?P<name>{_NAME})")
# "S. Madhavi / Section Officer (Estt.I) / 27/05/2025 10:15 AM", or the same on three lines
SIGNATURE = re.compile(
    rf"^[ \t]*(?P<ini>{_INI})[ \t]*(?P<name>{_NAME})[ \t]*(?:/|\n)[ \t]*"
    r"(?P<role>[^/\n]{3,80}?)[ \t]*(?:/|\n)[ \t]*\d{2}/\d{2}/\d{4}",
    re.M,
)
# the typed e-Office note sheet: date line, NAME[, I.A.S], POST — all capitals
TYPED_SIGNATURE = re.compile(
    r"^\d{2}/\d{2}/\d{4} \d{1,2}:\d{2} [AP]M\n"
    r"(?P<ini>(?:[A-Z]{1,2}\.\s?){1,4})\s*(?P<name>[A-Z]{3,}(?: [A-Z]{3,}){0,3})(?:, [A-Z.]+)?\n"
    r"(?P<role>[A-Z][A-Z .()&,-]{3,80})$",
    re.M,
)
_ROLE_AFTER = re.compile(
    r"^,\s*(?P<role>[A-Z][A-Za-z.()& -]{2,60}(?:,\s*[A-Z][A-Za-z.() -]{2,40}){0,2})"
)
OFFICE = re.compile(
    r"\b(?P<kind>Regional|District|Divisional|Zonal|Circle|Head|Sub-Divisional|Mandal)\s+Office,?\s+"
    r"(?P<station>[A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})?)"
)
# initials that are abbreviations, not a person's: "A.P. Gazette", "U.O. Note", "G.O. …"
_ABBREVIATIONS = frozenset({"ap", "uo", "go", "sl", "ms", "rt", "dt", "no", "puc", "ts", "gad"})
# initialled words that are not people: "A.P. State …", "G.O. Ms …"
_NOT_NAMES = frozenset(
    {
        "Government", "Department", "Office", "Officer", "Secretary", "Section", "State",
        "Gazette", "District", "Andhra", "Pradesh", "Telangana", "India", "Commissioner",
        "Director", "Collector", "Board", "Council", "Corporation", "Municipal", "Act",
        "Rules", "Rule", "Code", "Order", "Orders", "Memo", "Circular", "Notification",
        "Dated", "Dept", "Finance", "General", "School", "Education", "Urban", "Services",
        "For", "The", "Any", "All", "And", "Of", "Employees", "Transfers", "Note", "Ref",
    }
)  # fmt: skip


def _initials(raw: str | None) -> str:
    """'K. V.' → 'kv'; 'Ch.' → 'ch'; 'K V' → 'kv'."""
    return "".join(t for t in re.split(r"[.\s]+", (raw or "").lower()) if t)


def person_key(initials: str, name: str) -> str:
    """'K', 'Venkata Ramana' → 'k|venkata ramana' (initials in order, name words lower-case)."""
    return f"{_initials(initials)}|{' '.join(name.lower().split())}"


def officer_key(officer_id: str) -> str:
    return f"officer:{officer_id}"


def office_key(kind: str, station: str) -> str:
    return f"{kind.lower()} office|{' '.join(station.lower().split())}"


def name_key_of(name: str) -> str:
    """A recorded full name ("B. Suresh Kumar", "B. SURESH KUMAR") as initials|name words."""
    m = re.match(r"^\s*(?P<ini>(?:[A-Za-z]{1,2}\.\s?){1,4})\s*(?P<name>.+?)\s*$", name)
    if not m:
        return person_key("", name)
    return person_key(m.group("ini"), m.group("name"))


def _clean_role(role: str) -> str:
    role = role.strip().rstrip(",;.")
    return re.split(r"\s+(?:has|have|who|was|is|vide|in)\b", role)[0].strip().rstrip(",")


def _abbreviation(initials: str) -> bool:
    return _initials(initials) in _ABBREVIATIONS


def _is_name(name: str) -> bool:
    return not any(w in _NOT_NAMES for w in name.split())


def mentions(text: str, signers: Iterable[Signer] = (), *, loose: bool = True) -> list[Mention]:
    """Every person, officer and office the text names. A signature whose name is one of the
    paper's recorded signers resolves to that officer's ID; otherwise it stays a name. `loose`:
    also take initialled names written without an honorific ("Ch. Suresh Babu") — for typed
    e-Office papers only; OCR'd public orders give too many false ones ("B.Com", "Dy. Secy")."""
    officers = {name_key_of(s.name): s for s in signers}
    out: list[Mention] = []
    signed: set[str] = set()
    for pattern in (SIGNATURE, TYPED_SIGNATURE):
        for m in pattern.finditer(text):
            name = " ".join(w.capitalize() for w in m.group("name").split())
            nk = person_key(m.group("ini"), name)
            signed.add(nk)
            role = " ".join(m.group("role").split())
            role = role.title() if role.isupper() else role
            s = officers.get(nk)
            if s is not None:  # the e-Office ID, not the name, is the identity
                out.append(
                    Mention(
                        EntityKind.OFFICER, officer_key(s.officer_id), s.name, role or s.post,
                        signed=True, name_key=nk,
                    )
                )  # fmt: skip
            else:
                ini = " ".join(
                    f"{t.capitalize()}." for t in re.split(r"[.\s]+", m.group("ini")) if t
                )
                out.append(
                    Mention(EntityKind.PERSON, nk, f"{ini} {name}", role, signed=True, name_key=nk)
                )
    spans = []
    for m in PERSON.finditer(text):
        name = m.group("name")
        if not _is_name(name):
            continue
        spans.append(m.span())
        after = _ROLE_AFTER.match(text[m.end() : m.end() + 120])
        nk = person_key(m.group("ini") or "", name)
        out.append(
            Mention(
                EntityKind.PERSON, nk, m.group(0).strip(),
                _clean_role(after.group("role")) if after else "", name_key=nk,
            )
        )  # fmt: skip
    for m in INITIALLED.finditer(text) if loose else ():
        name = m.group("name")
        nk = person_key(m.group("ini"), name)
        inside = any(a <= m.start() < b for a, b in spans)
        if inside or not _is_name(name) or nk in signed or _abbreviation(m.group("ini")):
            continue
        out.append(Mention(EntityKind.PERSON, nk, m.group(0).strip(), name_key=nk))
    for m in OFFICE.finditer(text):
        out.append(
            Mention(EntityKind.OFFICE, office_key(m.group("kind"), m.group("station")),
                    m.group(0).rstrip(","))
        )  # fmt: skip
    return out


# "a request LIKE Sri Ch. Naveen Kumar's": the person is an example, not what the question is about
_EXAMPLE = re.compile(r"\b(?:like|similar to|such as|as in|as with|as that of)\s+(?:that of\s+)?$")


def _as_example(text: str, start: int) -> bool:
    return bool(_EXAMPLE.search(text[max(0, start - 30) : start].lower()))


@dataclass(frozen=True)
class QueryEntity:
    kind: EntityKind
    key: str  # a name key ("k|venkata ramana"), "|name words" (no initials), officer or office key
    surface: str
    partial: bool = False  # name without initials: matches every person with those name words


def in_question(
    text: str, known_names: Iterable[str] = (), officer_ids: Iterable[str] = ()
) -> list[QueryEntity]:
    """People, officers and offices a question is ABOUT. A person needs an honorific or initials;
    a bare name ("Venkata Ramana") counts only when it is exactly the name words of someone in the
    index (`known_names`), and then it is a partial match. An officer ID counts when the index
    knows it ("notes signed by V20"). A name given as an example ("a request like Sri Ch. Naveen
    Kumar's") is not what the question is about and is left out."""
    text = " ".join(text.split())
    out: list[QueryEntity] = []
    seen: set[str] = set()
    taken: list[tuple[int, int]] = []  # spans already read as a person (or deliberately skipped)

    def add(q: QueryEntity) -> None:
        if q.key not in seen:
            seen.add(q.key)
            out.append(q)

    def free(start: int) -> bool:
        return not any(a <= start < b for a, b in taken)

    for m in PERSON.finditer(text):
        taken.append(m.span())
        ini = _initials(m.group("ini"))
        if _is_name(m.group("name")) and not _as_example(text, m.start()):
            add(QueryEntity(EntityKind.PERSON, person_key(ini, m.group("name")),
                            m.group(0).strip(), partial=not ini))  # fmt: skip
    for m in INITIALLED.finditer(text):
        if not free(m.start()):
            continue
        taken.append(m.span())
        ok = _is_name(m.group("name")) and not _abbreviation(m.group("ini"))
        if ok and not _as_example(text, m.start()):
            add(QueryEntity(EntityKind.PERSON, person_key(m.group("ini"), m.group("name")),
                            m.group(0).strip()))  # fmt: skip
    low = text.lower()
    for n in sorted({n for n in known_names if n and len(n.split()) >= 2}, key=len, reverse=True):
        hit = re.search(rf"\b{re.escape(n)}\b", low)
        if hit and free(hit.start()) and not _as_example(text, hit.start()):
            taken.append(hit.span())
            add(QueryEntity(EntityKind.PERSON, f"|{n}", n.title(), partial=True))
    for oid in officer_ids:
        hit = re.search(rf"\b{re.escape(oid)}\b", text)
        if hit and not _as_example(text, hit.start()):
            add(QueryEntity(EntityKind.OFFICER, officer_key(oid), oid))
    for m in OFFICE.finditer(text):
        if not _as_example(text, m.start()):
            add(QueryEntity(EntityKind.OFFICE, office_key(m.group("kind"), m.group("station")),
                            m.group(0).rstrip(",")))  # fmt: skip
    return out


@dataclass
class EntityIndex:
    """Entity key → the records naming it (and how each names it). Not an access boundary."""

    by_key: dict[str, dict[str, list[Mention]]] = field(default_factory=dict)
    by_record: dict[str, list[Mention]] = field(default_factory=dict)
    names: dict[str, set[str]] = field(default_factory=dict)  # name key → entity keys

    def add(
        self, canonical_id: str, text: str, signers: Iterable[Signer] = (), *, loose: bool = True
    ) -> None:
        """(Re)index one record's text; idempotent per record."""
        self.remove(canonical_id)
        found = mentions(text, signers, loose=loose)
        self.by_record[canonical_id] = found
        for mt in found:
            self.by_key.setdefault(mt.key, {}).setdefault(canonical_id, []).append(mt)
            if mt.name_key:
                self.names.setdefault(mt.name_key, set()).add(mt.key)

    def remove(self, canonical_id: str) -> None:
        for mt in self.by_record.pop(canonical_id, []):
            recs = self.by_key.get(mt.key, {})
            recs.pop(canonical_id, None)
            if not recs:
                self.by_key.pop(mt.key, None)
                if mt.name_key in self.names:
                    self.names[mt.name_key].discard(mt.key)
                    if not self.names[mt.name_key]:
                        del self.names[mt.name_key]

    @classmethod
    def build(cls, texts: Mapping[str, str]) -> EntityIndex:
        idx = cls()
        for cid, text in texts.items():
            idx.add(cid, text)
        return idx

    def person_names(self) -> set[str]:
        """The name words of every person and officer (to recognise a bare name in a question)."""
        return {k.split("|", 1)[1] for k in self.names}

    def officer_ids(self) -> set[str]:
        return {k.removeprefix("officer:") for k in self.by_key if k.startswith("officer:")}

    def keys_for(self, q: QueryEntity) -> list[str]:
        """The entities a question's mention resolves to. A full name: the person with that key
        and every officer recorded under that name (separate entities: their IDs differ). A name
        without initials: everyone with those name words. An officer ID or office: itself."""
        if q.kind is not EntityKind.PERSON:
            return [q.key] if q.key in self.by_key else []
        if not q.partial:
            return sorted(k for k in self.names.get(q.key, ()) if k in self.by_key)
        words = q.key.split("|", 1)[1]
        return sorted(
            k
            for nk, keys in self.names.items()
            if nk.split("|", 1)[1] == words
            for k in keys
            if k in self.by_key
        )

    def records(self, key: str) -> dict[str, list[Mention]]:
        return dict(self.by_key.get(key, {}))
