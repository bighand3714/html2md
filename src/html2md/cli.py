"""CLI interface for html2md."""

from __future__ import annotations

import sys
from pathlib import Path

from .downloader import Downloader
from .errors import StrategyNotFoundError
from .pipeline import ConversionInfo, Pipeline
from .strategy import resolve_strategy


def main():
    """Entry point for the html2md CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="html2md",
        description="Convert Wiki HTML pages to Obsidian-compatible Markdown",
    )

    subparsers = parser.add_subparsers(dest="command")

    # ---- convert ----
    convert_parser = subparsers.add_parser(
        "convert", help="Convert HTML files or URLs to Markdown"
    )
    convert_parser.add_argument(
        "inputs",
        nargs="+",
        help="One or more input HTML files or URLs",
    )
    convert_parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output directory (default: same as source HTML)",
    )
    convert_parser.add_argument(
        "--strategy", "-s",
        default=None,
        help="Force a specific site strategy (e.g. wikipedia_en, fandom)",
    )
    convert_parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Strict mode: fail on first error",
    )
    convert_parser.add_argument(
        "--strategies-dir",
        default=None,
        help="Directory containing custom site strategy YAML files",
    )

    # ---- list-strategies ----
    list_parser = subparsers.add_parser(
        "list-strategies", help="List available site strategies"
    )
    list_parser.add_argument(
        "--strategies-dir",
        default=None,
        help="Directory containing custom site strategy YAML files",
    )

    args = parser.parse_args()

    if args.command == "convert":
        _handle_convert(args)
    elif args.command == "list-strategies":
        _handle_list_strategies(args)
    else:
        parser.print_help()


def _handle_convert(args) -> None:
    """Handle the 'convert' subcommand."""
    results: list[ConversionInfo] = []
    downloader = Downloader()

    for input_str in args.inputs:
        try:
            # Determine input type and get HTML path
            if Downloader.is_url(input_str):
                output_dir = (
                    Path(args.output) if args.output
                    else Path.cwd()
                )
                html_path = downloader.download(input_str, output_dir)
            else:
                html_path = Path(input_str)
                if not html_path.exists():
                    print(f"Error: File not found: {input_str}", file=sys.stderr)
                    continue

            # Resolve output directory
            output_dir = (
                Path(args.output) if args.output
                else html_path.parent
            )

            # Load HTML for strategy detection
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            # Determine site strategy
            if args.strategies_dir:
                sites_dir = Path(args.strategies_dir)
            else:
                sites_dir = None

            strategy = resolve_strategy(
                html=html_content,
                url_hint=input_str if Downloader.is_url(input_str) else None,
                strategy_name=args.strategy,
                sites_dir=sites_dir,
            )

            # Run pipeline
            pipeline = Pipeline(strategy, strict=args.strict)
            result = pipeline.run(html_path, output_dir)

            info = ConversionInfo(
                input_path=input_str,
                output_path=str(result.output_path),
                success=True,
                stats={
                    "notes": len(result.citation_result.notes),
                    "references": len(result.citation_result.references),
                    "warnings": len(result.warnings),
                },
                warnings=result.warnings,
            )
            results.append(info)

            # Print summary
            notes_n = len(result.citation_result.notes)
            refs_n = len(result.citation_result.references)
            print(
                f"OK  {input_str} → {result.output_path.name} "
                f"({notes_n} notes, {refs_n} refs)"
            )
            if result.warnings:
                for w in result.warnings:
                    print(f"    WARNING: {w}", file=sys.stderr)

        except StrategyNotFoundError as e:
            print(f"ERROR: {input_str}: {e}", file=sys.stderr)
            results.append(ConversionInfo(
                input_path=input_str, output_path=None,
                success=False, stats={}, warnings=[str(e)],
            ))
        except Exception as e:
            print(f"ERROR: {input_str}: {e}", file=sys.stderr)
            if args.strict:
                raise

    # Final summary
    succeeded = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    if len(results) > 1:
        print(f"\nDone: {succeeded} succeeded, {failed} failed")


def _handle_list_strategies(args) -> None:
    """Handle the 'list-strategies' subcommand."""
    from .strategy import SiteStrategy

    if args.strategies_dir:
        sites_dir = Path(args.strategies_dir)
    else:
        sites_dir = Path(__file__).resolve().parent.parent.parent / "sites"

    strategies = SiteStrategy.load_all(sites_dir)

    if not strategies:
        print("No site strategies found.")
        return

    print(f"Available site strategies ({len(strategies)}):")
    print()
    for site_id, strategy in strategies.items():
        urls = ", ".join(strategy.url_patterns) if strategy.url_patterns else "(any)"
        print(f"  {site_id:20s}  {strategy.name}")
        print(f"  {'':20s}  URL patterns: {urls}")
        print()


if __name__ == "__main__":
    main()
