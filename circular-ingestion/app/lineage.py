"""Circular lineage: which circulars supersede, withdraw, amend or refer to earlier ones.

Detection is deterministic. A circular's own reference numbers are read from the top of its first page.
Sentences with change wording ("in supersession of", "hereby repealed", "stands amended", "please refer
to") are scanned for the reference numbers they cite, which are then matched against the reference numbers
of ingested circulars. Detected links are proposals: obligations are retired only when a reviewer confirms
a SUPERSEDES or WITHDRAWS link.
"""
import re
import uuid
from dataclasses import dataclass

import numpy as np

RELATION_PRIORITY = {"WITHDRAWS": 3, "SUPERSEDES": 3, "AMENDS": 2, "REFERS_TO": 1}
RETIRING = {"SUPERSEDES", "WITHDRAWS"}
HEADER_CHARS = 700
LIST_WINDOW = 2500

# Reference numbers. Whitespace is allowed around slashes because PDF line wraps split them.
_SLASH = r"\s*/\s*"
_PATTERNS = [
    # IRDAI/F&I/CIR/MISC/142/11/2026, IRDAI/INT/GDL/MISC/004/ 01/2020, IRDAI/NL/GDL/98(01)/07/2026
    re.compile(r"IRDAI(?:" + _SLASH + r"[A-Za-z0-9&().\-]+){2,9}?" + _SLASH + r"(?:19|20)\d{2}\b"),
    # RBI/2026-27/305
    re.compile(r"RBI" + _SLASH + r"\d{4}-\d{2,4}" + _SLASH + r"\d{1,4}\b"),
    # DOR.STR.REC.257/21-04-177/2026-27, DoR.AML.REC.261/14.06.001/2026-27, DBR.No.BP.BC.36/21.04.048/2016-17
    re.compile(r"\b[A-Z][A-Za-z]{1,7}(?:\.\s?[A-Za-z]{1,8}){1,6}\.\s?\d{1,4}" + _SLASH + r"[\d.\-]+" + _SLASH
               + r"\d{4}-\d{2,4}\b"),
    # SEBI/HO/MRD/MRD-PoD-1/P/CIR/2024/123
    re.compile(r"SEBI" + _SLASH + r"HO(?:" + _SLASH + r"[A-Za-z0-9\-]+){1,7}?" + _SLASH + r"(?:19|20)\d{2}"
               + _SLASH + r"\d{1,5}\b"),
    # Gazette notifications: G.S.R. 846(E)
    re.compile(r"G\.\s?S\.\s?R\.\s?\d{1,5}\s?\(E\)"),
]

_RELATIONS = [
    ("WITHDRAWS", re.compile(r"\b(?:repeal(?:ed|s)?|rescind(?:ed|s)?|withdrawn|withdraws?|ceases? to (?:be in force|apply)"
                             r"|stands? (?:repealed|withdrawn|rescinded)|no longer (?:in force|applicable))\b", re.I)),
    ("SUPERSEDES", re.compile(r"\b(?:in supersession of|supersed(?:es|ed|ing)|stands? superseded|replac(?:es|ed) (?:the )?"
                              r"(?:earlier|previous|existing)?\s*(?:circular|guidelines|directions|master circular))\b", re.I)),
    ("AMENDS", re.compile(r"\b(?:amend(?:ed|s|ment(?:s)? to)|in partial modification of|shall be substituted|"
                          r"is (?:hereby )?modified|stands? modified|inserted after)\b", re.I)),
    ("REFERS_TO", re.compile(r"\b(?:please refer|refer(?:red)? to|vide (?:our )?(?:circular|notification|ref)|"
                             r"in terms of|as per (?:our )?(?:circular|guidelines))\b", re.I)),
]
_SENTENCE_END = re.compile(r"(?<=[.;:])\s+(?=[A-Z(\d])|\n\s*\n")


@dataclass
class Citation:
    relation: str
    identifier: str
    normalized: str
    page_number: int | None
    evidence: str


def normalize(identifier: str) -> str:
    """Upper case, no whitespace, numbers without leading zeros, and 2026-2027 written as 2026-27."""
    text = re.sub(r"\s+", "", identifier).upper()
    text = re.sub(r"\b(\d{4})-(\d{2})(\d{2})\b", lambda m: f"{m.group(1)}-{m.group(3)}", text)
    return "/".join(re.sub(r"\b0+(\d)", r"\1", part) for part in text.split("/"))


def find_identifiers(text: str) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            if not any(start <= match.start() < end for start, end, _ in found):
                found.append((match.start(), match.end(), " ".join(match.group().split())))
    return sorted(found)


_HEADER_END = re.compile(r"\b(?:subject|sub\s*[:.]|madam|dear|please refer|to,?\s*$)|विषय", re.I | re.M)


def own_identifiers(pages: list[tuple[int, str]], title: str = "") -> set[str]:
    """Reference numbers in the title or the letterhead identify the circular itself.

    The letterhead ends at the subject line or salutation, because a subject such as "Repeal of the
    Guidelines (IRDAI/INT/GDL/MISC/004/01/2020)" cites another circular. Numbers on a line with change
    wording are never the circular's own.
    """
    first = pages[0][1][:HEADER_CHARS] if pages else ""
    end = _HEADER_END.search(first)
    header = f"{title}\n{first[:end.start()] if end else first}"
    own = set()
    for start, end_index, identifier in find_identifiers(header):
        line_start = header.rfind("\n", 0, start) + 1
        line_end = header.find("\n", end_index)
        if _relation(header[line_start:line_end if line_end >= 0 else len(header)]) in (None, "REFERS_TO"):
            own.add(identifier)
    return own


def _relation(sentence: str) -> str | None:
    for relation, pattern in _RELATIONS:
        if pattern.search(sentence):
            return relation
    return None


def detect(pages: list[tuple[int, str]], own: set[str]) -> list[Citation]:
    """Citations of other circulars, with the strongest relation stated for each.

    A sentence such as "The following circulars shall stand repealed:" applies its relation to the
    reference numbers in the list that follows it.
    """
    own_normalized = {normalize(item) for item in own}
    best: dict[str, Citation] = {}
    for page_number, text in pages:
        starts = [0] + [match.end() for match in _SENTENCE_END.finditer(text)]
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(text)
            sentence = text[start:end]
            relation = _relation(sentence)
            if relation is None:
                continue
            window_end = end
            if re.search(r"\bfollowing\b|:\s*$", sentence, re.I) and relation != "REFERS_TO":
                window_end = min(len(text), end + LIST_WINDOW)
            window = text[start:window_end]
            for _, _, identifier in find_identifiers(window):
                key = normalize(identifier)
                if key in own_normalized:
                    continue
                current = best.get(key)
                if current is None or RELATION_PRIORITY[relation] > RELATION_PRIORITY[current.relation]:
                    best[key] = Citation(relation, identifier, key, page_number,
                                         " ".join(sentence.split())[:600])
    return sorted(best.values(), key=lambda item: (-RELATION_PRIORITY[item.relation], item.identifier))


# ---------------------------------------------------------------- what changed between two circulars

def _words(text: str) -> set[str]:
    """Content words, and every number: "within 14 days" and "within 7 days" must not look the same."""
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2 or word.isdigit()}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def diff_obligations(old: list[dict], new: list[dict], match_threshold: float = 0.85) -> list[dict]:
    """Pair the obligations of an earlier circular (old) with a later one (new).

    Pairs are matched greedily by embedding similarity. A pair whose wording barely differs is UNCHANGED,
    otherwise MODIFIED. Unpaired old obligations are REMOVED, unpaired new ones are NEW.
    """
    pairs: list[tuple[int, int, float]] = []
    if old and new:
        left = np.array([item["embedding"] for item in old], dtype=float)
        right = np.array([item["embedding"] for item in new], dtype=float)
        left /= np.where(np.linalg.norm(left, axis=1, keepdims=True) == 0, 1, np.linalg.norm(left, axis=1, keepdims=True))
        right /= np.where(np.linalg.norm(right, axis=1, keepdims=True) == 0, 1, np.linalg.norm(right, axis=1, keepdims=True))
        scores = left @ right.T
        used_old, used_new = set(), set()
        for flat in np.argsort(scores, axis=None)[::-1]:
            i, j = divmod(int(flat), scores.shape[1])
            if scores[i, j] < match_threshold:
                break
            if i in used_old or j in used_new:
                continue
            used_old.add(i)
            used_new.add(j)
            pairs.append((i, j, float(scores[i, j])))

    def view(item):
        return {key: item[key] for key in ("id", "summary", "quotedText", "pageNumber", "lifecycleStatus")}

    result = []
    for i, j, score in pairs:
        a, b = old[i], new[j]
        overlap = len(_words(a["summary"]) & _words(b["summary"])) / max(1, len(_words(a["summary"]) | _words(b["summary"])))
        same = overlap >= 0.85 and _numbers(a["summary"]) == _numbers(b["summary"])
        result.append({"change": "UNCHANGED" if same else "MODIFIED", "similarity": round(score, 3),
                       "before": view(a), "after": view(b)})
    paired_old = {i for i, _, _ in pairs}
    paired_new = {j for _, j, _ in pairs}
    result += [{"change": "REMOVED", "similarity": None, "before": view(item), "after": None}
               for index, item in enumerate(old) if index not in paired_old]
    result += [{"change": "NEW", "similarity": None, "before": None, "after": view(item)}
               for index, item in enumerate(new) if index not in paired_new]
    order = {"MODIFIED": 0, "NEW": 1, "REMOVED": 2, "UNCHANGED": 3}
    return sorted(result, key=lambda item: order[item["change"]])


def link_id(source_document_id: str, normalized: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"clauseiq:link:{source_document_id}:{normalized}"))
