"""CLI entry point for the extraction pipeline.

Subcommands: extraction0..4, assemble, audit, generate-data, extraction-all
"""

import argparse
from datetime import datetime, timezone

from dotenv import load_dotenv

from transition_extraction.config import load_config

load_dotenv()


def get_run_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def main():
    parser = argparse.ArgumentParser(description="US Diplomatic Transition Extraction Pipeline")
    parser.add_argument("--config", default="input/extraction_config.yaml", help="Path to config YAML")
    parser.add_argument("--countries", default=None, help="Comma-separated list of countries to process")
    parser.add_argument("--dry-run", action="store_true", help="Estimate costs without making API calls (extraction2, extraction4)")
    parser.add_argument("--force", action="store_true", help="Re-run API calls even if output already exists (extraction2, extraction4)")

    subparsers = parser.add_subparsers(dest="command", help="Pipeline stage to run")
    subparsers.add_parser("extraction0", help="Country name resolution")
    subparsers.add_parser("extraction1", help="Preprocessing")
    subparsers.add_parser("extraction2", help="LLM extraction (Sonnet)")
    subparsers.add_parser("extraction3", help="Quote verification")
    subparsers.add_parser("extraction4", help="LLM reconciliation (Opus)")
    subparsers.add_parser("assemble", help="Final output assembly")
    subparsers.add_parser("audit", help="Generate HTML audit report")
    gen_parser = subparsers.add_parser("generate-data", help="Generate all data product CSVs")
    gen_parser.add_argument("--release-date", default=None, help="Codebook date (YYYY-MM-DD); defaults to today")
    subparsers.add_parser("extraction-all", help="Run all extraction stages sequentially")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    config = load_config(args.config)
    countries_filter = [c.strip() for c in args.countries.split(",")] if args.countries else None
    run_timestamp = get_run_timestamp()

    if args.force:
        config.api.skip_existing = False

    if args.command == "extraction0":
        from transition_extraction.stage0_resolve import run_stage0
        run_stage0(config)

    elif args.command == "extraction1":
        from transition_extraction.stage1_preprocess import run_stage1
        run_stage1(config, countries_filter)

    elif args.command == "extraction2":
        from transition_extraction.stage2_extract import run_stage2
        run_stage2(config, run_timestamp, countries_filter, args.dry_run)

    elif args.command == "extraction3":
        from transition_extraction.stage3_verify import run_stage3
        run_stage3(config, countries_filter)

    elif args.command == "extraction4":
        from transition_extraction.stage4_reconcile import run_stage4
        run_stage4(config, run_timestamp, countries_filter, args.dry_run)

    elif args.command == "assemble":
        from transition_extraction.assemble import run_assemble
        run_assemble(config, run_timestamp, countries_filter)

    elif args.command == "audit":
        from transition_extraction.audit_report import run_audit_report
        run_audit_report(config, countries_filter)

    elif args.command == "generate-data":
        from data_assembly.generate import generate_all_datasets
        from data_assembly.state_codes import StateCodeResolver
        from data_assembly.version import get_version

        version = get_version()
        transitions_csv = config.paths.output_dir / "local" / "final" / "assembled_transitions.csv"
        if not transitions_csv.exists():
            print(f"Error: {transitions_csv} not found. Run 'assemble' first.")
            return

        resolver = StateCodeResolver(
            config.paths.cow_raw,
            config.paths.gw_raw,
            config.paths.state_system_codes,
            gw_supplement=config.paths.gw_supplement,
        )
        warnings = resolver.validate()
        if warnings:
            print("Mapping validation warnings:")
            for w in warnings:
                print(f"  {w}")
            print()

        import csv as csv_mod
        with open(transitions_csv, newline="") as f:
            usdos_names = {row["state_dept_name"].strip() for row in csv_mod.DictReader(f)}
        coverage = resolver.diagnose_coverage(usdos_names)
        if coverage:
            print("Coverage diagnostics:")
            for msg in coverage:
                print(f"  {msg}")
            print()

        output_dir = config.repo_root / "data" / f"v{version}"
        print(f"Generating data product v{version} in {output_dir}\n")
        generate_all_datasets(resolver, transitions_csv, output_dir, version, release_date=args.release_date)

        from data_assembly.generate_web import generate_web_sources
        print("\nGenerating web sources...")
        generate_web_sources(output_dir, version)
        print("Done.")

    elif args.command == "extraction-all":
        from transition_extraction.stage0_resolve import run_stage0
        from transition_extraction.stage1_preprocess import run_stage1
        from transition_extraction.stage2_extract import run_stage2
        from transition_extraction.stage3_verify import run_stage3
        from transition_extraction.stage4_reconcile import run_stage4
        from transition_extraction.assemble import run_assemble

        print(f"Run timestamp: {run_timestamp}\n")

        print("=" * 60)
        run_stage0(config)
        print()

        print("=" * 60)
        run_stage1(config, countries_filter)
        print()

        if args.dry_run:
            print("=" * 60)
            run_stage2(config, run_timestamp, countries_filter, dry_run=True)
            print()
            print("=" * 60)
            run_stage4(config, run_timestamp, countries_filter, dry_run=True)
            return

        print("=" * 60)
        run_stage2(config, run_timestamp, countries_filter)
        print()

        print("=" * 60)
        run_stage3(config, countries_filter)
        print()

        print("=" * 60)
        run_stage4(config, run_timestamp, countries_filter)
        print()

        print("=" * 60)
        run_assemble(config, run_timestamp, countries_filter)


if __name__ == "__main__":
    main()
