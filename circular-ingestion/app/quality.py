"""Extraction quality per circular: where obligation extraction is weak and needs a human look."""
import re
from collections import defaultdict

import psycopg

LOW_CONFIDENCE = 0.6
THRESHOLDS = {"rejection": 0.3, "lowConfidence": 0.25, "duplicates": 0.2}


def _words(text: str) -> frozenset[str]:
    return frozenset(word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2)


def _duplicates(summaries: list[str]) -> int:
    """Obligations whose wording nearly repeats an earlier obligation in the same circular."""
    seen: list[frozenset[str]] = []
    count = 0
    for words in map(_words, summaries):
        if words and any(len(words & other) / len(words | other) >= 0.8 for other in seen):
            count += 1
        seen.append(words)
    return count


def flags(item: dict) -> list[str]:
    result = []
    if item["status"] in ("FAILED",) or item["eventStatus"] in ("FAILED", "DEAD_LETTERED"):
        result.append("Processing failed")
    if item["status"] == "COMPLETED" and item["pages"] and item["obligations"] == 0:
        result.append("No obligations extracted")
    if item["rejectionRate"] is not None and item["rejectionRate"] > THRESHOLDS["rejection"]:
        result.append("Many quotes failed citation checks")
    if item["lowConfidenceShare"] is not None and item["lowConfidenceShare"] > THRESHOLDS["lowConfidence"]:
        result.append("Low model confidence")
    if item["duplicateShare"] is not None and item["duplicateShare"] > THRESHOLDS["duplicates"]:
        result.append("Repeated obligations")
    if item["ocrPages"]:
        result.append("OCR used")
    return result


def report(database_url: str) -> dict:
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        versions = connection.execute(
            """
            SELECT v.id, d.id, d.regulator, d.title, d.source_url, v.processing_status, v.page_count, v.ocr_page_count,
                   v.obligation_count, v.rejected_obligation_count, v.processed_at,
                   e.status, e.attempts, e.last_error
            FROM regulatory_document_version v
            JOIN regulatory_document d ON d.id = v.document_id
            LEFT JOIN LATERAL (SELECT status, attempts, last_error FROM processed_event
                               WHERE document_version_id = v.id ORDER BY started_at DESC LIMIT 1) e ON true
            ORDER BY v.processed_at DESC NULLS FIRST
            """).fetchall()
        obligations = defaultdict(list)
        for version_id, summary, confidence, method, deadline in connection.execute(
                "SELECT document_version_id, summary, confidence, extraction_method, deadline FROM obligation"):
            obligations[version_id].append((summary, confidence, method, deadline))

    items = []
    for row in versions:
        found = obligations.get(row[0], [])
        accepted = len(found)
        rejected = row[9] or 0
        confidences = [item[1] for item in found]
        duplicates = _duplicates([item[0] for item in found])
        item = {
            "documentVersionId": row[0], "documentId": row[1], "regulator": row[2], "title": row[3],
            "sourceUrl": row[4], "status": row[5], "pages": row[6], "ocrPages": row[7],
            "obligations": accepted, "rejected": rejected,
            "rejectionRate": round(rejected / (accepted + rejected), 3) if accepted + rejected else None,
            "meanConfidence": round(sum(confidences) / accepted, 3) if accepted else None,
            "lowConfidenceShare": round(sum(1 for value in confidences if value < LOW_CONFIDENCE) / accepted, 3)
            if accepted else None,
            "duplicates": duplicates, "duplicateShare": round(duplicates / accepted, 3) if accepted else None,
            "withDeadline": sum(1 for item in found if item[3]),
            "method": ", ".join(sorted({item[2] for item in found})) or None,
            "processedAt": row[10], "eventStatus": row[11], "attempts": row[12], "lastError": row[13],
        }
        item["flags"] = flags(item)
        items.append(item)

    completed = [item for item in items if item["status"] == "COMPLETED"]
    accepted = sum(item["obligations"] for item in completed)
    rejected = sum(item["rejected"] for item in completed)
    confidences = [confidence for version in completed for _, confidence, _, _ in obligations.get(version["documentVersionId"], [])]
    known_ocr = [item for item in completed if item["ocrPages"] is not None]
    summary = {
        "circulars": len(items), "completed": len(completed),
        "failed": sum(1 for item in items if "Processing failed" in item["flags"]),
        "obligations": accepted, "rejected": rejected,
        "rejectionRate": round(rejected / (accepted + rejected), 3) if accepted + rejected else None,
        "meanConfidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
        "lowConfidenceShare": round(sum(1 for value in confidences if value < LOW_CONFIDENCE) / len(confidences), 3)
        if confidences else None,
        "duplicates": sum(item["duplicates"] for item in completed),
        "ocrCirculars": sum(1 for item in known_ocr if item["ocrPages"]),
        "ocrUnknown": len(completed) - len(known_ocr),
        "flagged": sum(1 for item in items if item["flags"]),
        "thresholds": {"rejectionRate": THRESHOLDS["rejection"], "lowConfidenceShare": THRESHOLDS["lowConfidence"],
                       "duplicateShare": THRESHOLDS["duplicates"], "lowConfidenceBelow": LOW_CONFIDENCE},
    }
    return {"summary": summary, "circulars": items}
