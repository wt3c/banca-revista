from __future__ import annotations

import json
from pathlib import Path

from banca_revista.metadata import ComicMetadata, best_effort_metadata, metadata_from_ocr, parse_comic_metadata
from banca_revista.ocr import MetadataCandidate, OcrReport


def test_comic_metadata_uses_calibre_compatible_comment() -> None:
    metadata = ComicMetadata(
        title="SIDOOH - Volume 01",
        authors=("Tsutomu Takahashi",),
        series="SIDOOH",
        volume=1,
        isbn="9784088768120",
        publisher="Panini Comics",
        tags=("Mangá", "Ação"),
    )

    comment = json.loads(metadata.to_comment())["ComicBookInfo/1.0"]

    assert comment["title"] == "SIDOOH - Volume 01"
    assert comment["credits"] == [{"person": "Tsutomu Takahashi", "role": "Writer"}]
    assert comment["series"] == "SIDOOH"
    assert comment["volume"] == 1
    assert comment["isbn"] == "9784088768120"
    assert comment["publisher"] == "Panini Comics"
    assert comment["tags"] == ["Mangá", "Ação"]


def test_metadata_from_ocr_promotes_only_confirmed_fields() -> None:
    report = OcrReport(
        source=Path("SIDOOH - Volume 01 [Packs de HQs].cbr"),
        pages=(),
        candidates=(
            MetadataCandidate("title", "SIDOOH", 0.98, "nome"),
            MetadataCandidate("volume", "01", 0.99, "nome"),
            MetadataCandidate("isbn", "9784088768120", 0.99, "OCR"),
            MetadataCandidate("author_candidate", "puro Takalasth", 0.55, "OCR"),
            MetadataCandidate("author", "高橋ツトム", 0.99, "NDL"),
            MetadataCandidate("publisher", "集英社", 0.99, "NDL"),
        ),
    )

    metadata = metadata_from_ocr(report, tags=("Mangá",))

    assert metadata.title == "SIDOOH - Volume 01"
    assert metadata.authors == ("高橋ツトム",)
    assert metadata.series == "SIDOOH"
    assert metadata.volume == 1
    assert metadata.isbn == "9784088768120"
    assert metadata.publisher == "集英社"
    assert metadata.tags == ("Mangá",)

    localized = metadata_from_ocr(report, author="Tsutomu Takahashi", publisher="Panini Comics")
    assert localized.authors == ("Tsutomu Takahashi",)
    assert localized.publisher == "Panini Comics"


def test_parse_and_best_effort_preserve_existing_metadata() -> None:
    existing = ComicMetadata(
        title="Edição localizada",
        authors=("Autora Confirmada",),
        publisher="Editora Local",
    )
    parsed = parse_comic_metadata(existing.to_comment())

    merged = best_effort_metadata(None, fallback_title="arquivo", existing=parsed)

    assert merged == existing
