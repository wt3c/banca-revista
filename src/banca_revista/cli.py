"""Interface de linha de comando do Banca Revista."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from banca_revista.archive import ConversionError, convert_rar_to_cbz, inspect_rar
from banca_revista.batch import DEFAULT_WORKERS, next_report_path, run_batch, save_report
from banca_revista.cbr import convert_to_cbr
from banca_revista.metadata import ComicMetadata, create_metadata_cbr, metadata_from_ocr
from banca_revista.ocr import analyze_cbr
from banca_revista.pipeline import process_to_library


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normaliza quadrinhos para uso no Calibre")
    subcommands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subcommands.add_parser("inspect", help="inspeciona um CBR/RAR sem alterá-lo")
    inspect_parser.add_argument("source", type=Path)

    convert_parser = subcommands.add_parser("convert", help="converte um CBR/RAR em CBZ")
    convert_parser.add_argument("source", type=Path)
    convert_parser.add_argument("output", type=Path)

    ocr_parser = subcommands.add_parser("ocr", help="extrai candidatos de metadados das primeiras páginas")
    ocr_parser.add_argument("source", type=Path)
    ocr_parser.add_argument("--pages", type=int, default=2, help="quantidade de páginas analisadas (padrão: 2)")
    ocr_parser.add_argument(
        "--lookup-isbn",
        action="store_true",
        help="consulta o catálogo NDL pelo ISBN detectado; nenhuma imagem é enviada",
    )

    metadata_parser = subcommands.add_parser("metadata", help="cria uma cópia CBR com metadados ComicBookInfo")
    metadata_parser.add_argument("source", type=Path)
    metadata_parser.add_argument("output", type=Path)
    metadata_parser.add_argument("--title", required=True)
    metadata_parser.add_argument("--author", action="append", default=[])
    metadata_parser.add_argument("--series")
    metadata_parser.add_argument("--volume", type=float)
    metadata_parser.add_argument("--isbn")
    metadata_parser.add_argument("--publisher")
    metadata_parser.add_argument("--tag", action="append", default=[])

    enrich_parser = subcommands.add_parser(
        "enrich",
        help="detecta metadados, consulta o NDL pelo ISBN e cria um novo CBR",
    )
    enrich_parser.add_argument("source", type=Path)
    enrich_parser.add_argument("output", type=Path)
    enrich_parser.add_argument("--author", help="substitui a grafia de autor devolvida pelo catálogo")
    enrich_parser.add_argument("--publisher", help="substitui a editora da edição associada ao ISBN")
    enrich_parser.add_argument("--tag", action="append", default=[])

    to_cbr_parser = subcommands.add_parser("to-cbr", help="converte PDF ou ZIP em um novo CBR")
    to_cbr_parser.add_argument("source", type=Path)
    to_cbr_parser.add_argument("output", type=Path)
    to_cbr_parser.add_argument(
        "--pdf-mode",
        choices=("auto", "lossless", "render"),
        default="auto",
        help="estratégia para PDF (padrão: auto)",
    )
    to_cbr_parser.add_argument("--dpi", type=int, default=200, help="resolução do modo render (padrão: 200)")

    batch_parser = subcommands.add_parser(
        "batch-to-cbr",
        help="converte PDF/ZIP/CBZ e processa todos os CBRs de uma pasta",
    )
    batch_parser.add_argument("base", type=Path)
    batch_parser.add_argument("output_dir", type=Path)
    batch_parser.add_argument("--execute", action="store_true", help="executa o plano; sem esta opção apenas simula")
    batch_parser.add_argument("--report", type=Path, help="arquivo JSON do relatório durante a execução")
    batch_parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"quantidade de processos paralelos (padrão: {DEFAULT_WORKERS})",
    )
    batch_parser.add_argument(
        "--no-lookup-isbn",
        action="store_true",
        help="não consulta o catálogo NDL pelos ISBNs encontrados",
    )

    process_parser = subcommands.add_parser(
        "process",
        help="normaliza, aplica OCR/metadados e publica um CBR",
    )
    process_parser.add_argument("source", type=Path)
    process_parser.add_argument("output", type=Path)
    process_parser.add_argument("--no-lookup-isbn", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "ocr":
            print(analyze_cbr(args.source, page_count=args.pages, lookup_isbn=args.lookup_isbn).to_json())
            return 0
        if args.command == "metadata":
            metadata = ComicMetadata(
                title=args.title,
                authors=tuple(args.author),
                series=args.series,
                volume=args.volume,
                isbn=args.isbn,
                publisher=args.publisher,
                tags=tuple(args.tag),
            )
            output = create_metadata_cbr(args.source, args.output, metadata)
            print(f"CBR com metadados criado: {output}")
            return 0
        if args.command == "enrich":
            report = analyze_cbr(args.source, lookup_isbn=True)
            metadata = metadata_from_ocr(
                report,
                author=args.author,
                publisher=args.publisher,
                tags=tuple(args.tag),
            )
            output = create_metadata_cbr(args.source, args.output, metadata)
            print(f"CBR enriquecido criado: {output}")
            return 0
        if args.command == "to-cbr":
            result = convert_to_cbr(args.source, args.output, pdf_mode=args.pdf_mode, dpi=args.dpi)
            print(f"CBR criado: {result.output}")
            print(f"origem detectada: {result.input_format}")
            print(f"estratégia: {result.strategy}")
            print(f"páginas: {result.page_count}")
            print(f"capa: {result.first_page}")
            return 0
        if args.command == "batch-to-cbr":
            report = run_batch(
                args.base,
                args.output_dir,
                dry_run=not args.execute,
                lookup_isbn=not args.no_lookup_isbn,
                workers=args.workers,
            )
            print(report.to_json())
            if args.execute:
                report_path = args.report or next_report_path(args.output_dir)
                saved = save_report(report, report_path)
                print(f"relatório salvo: {saved}")
            return 0
        if args.command == "process":
            result = process_to_library(
                args.source,
                args.output,
                lookup_isbn=not args.no_lookup_isbn,
            )
            print(f"CBR processado: {result.output}")
            print(f"estratégia: {result.strategy}")
            print(f"páginas: {result.page_count}")
            if result.warnings:
                print(f"avisos: {' | '.join(result.warnings)}")
            return 0

        inspection = inspect_rar(args.source)
        print(f"formato: {inspection.archive_format}")
        print(f"páginas: {len(inspection.pages)}")
        print(f"primeira página: {inspection.pages[0].source_name}")
        print(f"pasta interna comum: {inspection.common_parent or 'nenhuma'}")

        if args.command == "convert":
            result = convert_rar_to_cbz(inspection, args.output)
            print(f"CBZ criado: {result.output}")
            print(f"primeira página no CBZ: {result.first_page}")
    except (ConversionError, OSError) as error:
        print(f"erro: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
