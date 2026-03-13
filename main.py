"""CLI entry point for the extraction pipeline.

Subcommands: stage0, stage1, stage2, stage3, stage4, assemble, run-all
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
    parser.add_argument("--dry-run", action="store_true", help="Estimate costs without making API calls (stages 2, 4)")
    parser.add_argument("--force", action="store_true", help="Re-run API calls even if output already exists (stages 2, 4)")

    subparsers = parser.add_subparsers(dest="command", help="Pipeline stage to run")
    subparsers.add_parser("stage0", help="Country name resolution")
    subparsers.add_parser("stage1", help="Preprocessing")
    subparsers.add_parser("stage2", help="LLM extraction (Sonnet)")
    subparsers.add_parser("stage3", help="Quote verification")
    subparsers.add_parser("stage4", help="LLM reconciliation (Opus)")
    subparsers.add_parser("assemble", help="Final output assembly")
    subparsers.add_parser("audit", help="Generate HTML audit report")
    panel_parser = subparsers.add_parser("build-panel", help="Build interval-level panel dataset")
    panel_parser.add_argument("--system", required=True, choices=["cow", "gw"], help="State system (cow or gw)")
    subparsers.add_parser("diagnose", help="Compare CSV vs assembled on legation-or-higher ranges")
    subparsers.add_parser("run-all", help="Run all stages sequentially")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    config = load_config(args.config)
    countries_filter = [c.strip() for c in args.countries.split(",")] if args.countries else None
    run_timestamp = get_run_timestamp()

    if args.force:
        config.api.skip_existing = False

    if args.command == "stage0":
        from transition_extraction.stage0_resolve import run_stage0
        run_stage0(config)

    elif args.command == "stage1":
        from transition_extraction.stage1_preprocess import run_stage1
        run_stage1(config, countries_filter)

    elif args.command == "stage2":
        from transition_extraction.stage2_extract import run_stage2
        run_stage2(config, run_timestamp, countries_filter, args.dry_run)

    elif args.command == "stage3":
        from transition_extraction.stage3_verify import run_stage3
        run_stage3(config, countries_filter)

    elif args.command == "stage4":
        from transition_extraction.stage4_reconcile import run_stage4
        run_stage4(config, run_timestamp, countries_filter, args.dry_run)

    elif args.command == "assemble":
        from transition_extraction.assemble import run_assemble
        run_assemble(config, run_timestamp, countries_filter)

    elif args.command == "audit":
        from transition_extraction.audit_report import run_audit_report
        run_audit_report(config, countries_filter)

    elif args.command == "build-panel":
        from data_assembly.panel import build_panel, write_panel_csv
        from data_assembly.state_codes import StateCodeResolver
        from data_assembly.diagnostics import print_diagnostics

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

        rows = build_panel(resolver, config.paths.transitions_csv, args.system)
        output_path = config.paths.output_dir / f"panel_{args.system}.csv"
        config.paths.output_dir.mkdir(parents=True, exist_ok=True)
        write_panel_csv(rows, output_path)
        print(f"Wrote {len(rows)} rows to {output_path}")

        # Compare against old reference _mod file
        if args.system == "cow":
            ref_path = config.repo_root / "input" / "cowstates_mod.csv"
        else:
            ref_path = config.repo_root / "input" / "gwstates_mod.csv"
        if ref_path.exists():
            print_diagnostics(rows, ref_path, args.system)

    elif args.command == "diagnose":
        from transition_extraction.diagnose import run_diagnose
        run_diagnose(config, countries_filter)

    elif args.command == "run-all":
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
