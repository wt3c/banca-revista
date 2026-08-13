"""Consulta opcional a catálogos bibliográficos por ISBN."""

from __future__ import annotations

import html
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO

NDL_ENDPOINT = "https://ndlsearch.ndl.go.jp/api/sru"
_SRU = "http://www.loc.gov/zing/srw/"
_DCTERMS = "http://purl.org/dc/terms/"
_DC = "http://purl.org/dc/elements/1.1/"
_DCNDL = "http://ndl.go.jp/dcndl/terms/"
_FOAF = "http://xmlns.com/foaf/0.1/"


class CatalogError(RuntimeError):
    """Erro esperado durante uma consulta bibliográfica opcional."""


@dataclass(frozen=True)
class CatalogMetadata:
    """Campos devolvidos pelo catálogo oficial."""

    title: str | None = None
    author: str | None = None
    publisher: str | None = None
    volume: str | None = None
    publication_date: str | None = None
    language: str | None = None


def lookup_ndl_isbn(
    isbn: str,
    *,
    timeout: float = 20,
    opener: Callable[..., BinaryIO] = urllib.request.urlopen,
) -> CatalogMetadata | None:
    """Consulta a Biblioteca Nacional do Japão enviando somente o ISBN."""
    query = urllib.parse.urlencode(
        {
            "operation": "searchRetrieve",
            "query": f"isbn={isbn}",
            "recordSchema": "dcndl",
        }
    )
    request = urllib.request.Request(
        f"{NDL_ENDPOINT}?{query}",
        headers={"User-Agent": "banca-revista/0.1"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = response.read()
    except (OSError, urllib.error.URLError) as error:
        raise CatalogError(f"falha ao consultar o catálogo NDL: {error}") from error
    return parse_ndl_response(payload)


def parse_ndl_response(payload: bytes) -> CatalogMetadata | None:
    """Converte a resposta SRU, cujo RDF vem escapado dentro de recordData."""
    try:
        response = ET.fromstring(payload)
        if response.findtext(f"{{{_SRU}}}numberOfRecords") == "0":
            return None
        record_data = response.find(f".//{{{_SRU}}}recordData")
        if record_data is None or not record_data.text:
            return None
        rdf = ET.fromstring(html.unescape(record_data.text).strip())
    except ET.ParseError as error:
        raise CatalogError("o catálogo NDL devolveu XML inválido") from error

    return CatalogMetadata(
        title=_text(rdf, f".//{{{_DCTERMS}}}title"),
        author=_clean_author(
            _text(rdf, f".//{{{_DC}}}creator") or _text(rdf, f".//{{{_DCTERMS}}}creator//{{{_FOAF}}}name")
        ),
        publisher=_text(rdf, f".//{{{_DCTERMS}}}publisher//{{{_FOAF}}}name"),
        volume=_text(rdf, f".//{{{_DCNDL}}}volume//{{http://www.w3.org/1999/02/22-rdf-syntax-ns#}}value"),
        publication_date=_text(rdf, f".//{{{_DCTERMS}}}date"),
        language=_text(rdf, f".//{{{_DCTERMS}}}language"),
    )


def _text(root: ET.Element, path: str) -> str | None:
    value = root.findtext(path)
    return value.strip() if value and value.strip() else None


def _clean_author(value: str | None) -> str | None:
    if value is None:
        return None
    return value.removesuffix(" 著").strip()
