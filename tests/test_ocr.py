from __future__ import annotations

import json
from pathlib import Path

from banca_revista.ocr import OcrReport, PageOcr, author_candidates, find_isbn, infer_candidates


def test_find_isbn_prefers_valid_isbn13() -> None:
    text = "código 9784088768120 e ISBN4-08-876812-4"

    assert find_isbn(text) == "9784088768120"


def test_find_isbn_rejects_invalid_check_digit() -> None:
    assert find_isbn("ISBN 9784088768121") is None


def test_author_candidates_do_not_claim_editorial_labels() -> None:
    texts = ("Tsutomu Takahashi\nPlanet Manga\nSIDOOH 1",)

    assert author_candidates(texts) == ("Tsutomu Takahashi",)


def test_infer_candidates_keeps_evidence_and_confidence() -> None:
    pages = [
        PageOcr(page="(000).jpg", full_text="SIDOOH", author_region_texts=("Tsutomu Takahashi",)),
        PageOcr(page="(200).jpg", full_text="9784088768120"),
    ]

    candidates = infer_candidates("SIDOOH - Volume 01 [Packs de HQs].cbr", pages)

    assert [(item.field, item.value) for item in candidates] == [
        ("title", "SIDOOH"),
        ("volume", "01"),
        ("isbn", "9784088768120"),
        ("author_candidate", "Tsutomu Takahashi"),
    ]
    assert candidates[2].page == "(200).jpg"
    assert candidates[3].confidence < candidates[2].confidence


def test_report_serializes_path_as_json_string(tmp_path: Path) -> None:
    report = OcrReport(source=tmp_path / "comic.cbr", pages=(), candidates=())

    assert json.loads(report.to_json())["source"] == str(tmp_path / "comic.cbr")
