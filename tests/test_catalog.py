from __future__ import annotations

import html

from banca_revista.catalog import parse_ndl_response


def test_parse_ndl_response_extracts_official_metadata() -> None:
    rdf = """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:dcterms="http://purl.org/dc/terms/"
      xmlns:dcndl="http://ndl.go.jp/dcndl/terms/"
      xmlns:foaf="http://xmlns.com/foaf/0.1/">
      <dcndl:BibResource>
        <dcterms:title>Sidooh士道. 1</dcterms:title>
        <dc:creator>高橋ツトム 著</dc:creator>
        <dcterms:publisher><foaf:Agent><foaf:name>集英社</foaf:name></foaf:Agent></dcterms:publisher>
        <dcndl:volume><rdf:Description><rdf:value>1</rdf:value></rdf:Description></dcndl:volume>
        <dcterms:date>2005.6</dcterms:date>
        <dcterms:language>jpn</dcterms:language>
      </dcndl:BibResource>
    </rdf:RDF>"""
    payload = f"""<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
      <numberOfRecords>1</numberOfRecords>
      <records><record><recordData>{html.escape(rdf)}</recordData></record></records>
    </searchRetrieveResponse>""".encode()

    metadata = parse_ndl_response(payload)

    assert metadata is not None
    assert metadata.title == "Sidooh士道. 1"
    assert metadata.author == "高橋ツトム"
    assert metadata.publisher == "集英社"
    assert metadata.volume == "1"
    assert metadata.publication_date == "2005.6"
    assert metadata.language == "jpn"


def test_parse_ndl_response_handles_no_results() -> None:
    payload = b'<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"><numberOfRecords>0</numberOfRecords></searchRetrieveResponse>'

    assert parse_ndl_response(payload) is None
