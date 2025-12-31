"""
CLI entry point for extraction cascade.

Usage:
    python -m extraction_cascade extract <url> [--intent <template>]
    python -m extraction_cascade list-templates
    python -m extraction_cascade stats [--intent <template>]
"""

import argparse
import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extraction_cascade.orchestrator import CascadeOrchestrator, CascadeConfig
from extraction_cascade.approval.cli_approval import CLIApprovalCallback, VerboseCLICallback
from extraction_cascade.storage.provenance_store import ProvenanceStore


def cmd_extract(args):
    """Extract data from one or more URLs."""
    from vision_extractor.storage import TemplateStorage

    # Load intent
    storage = TemplateStorage()
    intent = storage.load(args.intent)

    if not intent:
        print(f"Error: Template '{args.intent}' not found")
        print("Use 'python -m extraction_cascade list-templates' to see available templates")
        sys.exit(1)

    # Create config
    config = CascadeConfig(
        enable_browser_agent=not args.no_browser,
        enable_vision=not args.no_vision,
        stop_on_complete=not args.all_tiers
    )

    # Handle single or multiple URLs
    urls = args.url if isinstance(args.url, list) else [args.url]
    all_results = []

    for i, url in enumerate(urls):
        if len(urls) > 1:
            print(f"\n{'='*60}")
            print(f"[{i+1}/{len(urls)}] Extracting from: {url}")
            print(f"{'='*60}")
        else:
            print(f"\nExtracting from: {url}")
        print(f"Template: {args.intent}")
        print()

        # Create fresh callback and orchestrator for each URL (to reset state)
        if args.auto:
            from extraction_cascade.approval.callback import AutoApprovalCallback
            callback = AutoApprovalCallback(max_cost=args.max_cost)
        elif args.verbose:
            callback = VerboseCLICallback(save_screenshots=args.save_screenshots)
        else:
            callback = CLIApprovalCallback(save_screenshots=args.save_screenshots)

        orchestrator = CascadeOrchestrator(
            intent=intent,
            approval_callback=callback,
            config=config
        )

        try:
            session = orchestrator.extract(url)
        except Exception as e:
            print(f"Error extracting from {url}: {e}")
            continue

        # Save provenance
        if not args.no_provenance:
            store = ProvenanceStore()
            store.save(session.get_provenance())

        # Collect results
        result = session.get_result()
        result['_url'] = url  # Add source URL to result
        all_results.append(result)
        provenance = session.get_provenance()

        if not args.output:
            _print_template_results(intent, result, provenance)

    # Output results
    if args.output:
        output_data = all_results if len(all_results) > 1 else all_results[0]
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, default=str)
        print(f"\nResults saved to: {args.output}")
        if len(urls) > 1:
            print(f"  ({len(urls)} URLs processed)")


def cmd_list_templates(args):
    """List available extraction templates."""
    from vision_extractor.storage import TemplateStorage

    storage = TemplateStorage()
    templates = storage.list_templates()

    if not templates:
        print("No templates found.")
        print("Create templates in config/extraction_templates/")
        return

    print("\nAvailable templates:")
    print("-"*40)
    for name in templates:
        intent = storage.load(name)
        if intent:
            fields = [f.name for f in intent.fields]
            print(f"\n  {name}")
            print(f"    Fields: {', '.join(fields[:5])}")
            if len(fields) > 5:
                print(f"            ... and {len(fields) - 5} more")


def cmd_stats(args):
    """Show extraction statistics."""
    store = ProvenanceStore()
    calibration = store.get_calibration_data(args.intent)

    if not calibration:
        print("No calibration data found.")
        print("Run some extractions first.")
        return

    if args.intent:
        _print_intent_stats(args.intent, calibration)
    else:
        print("\nCalibration data by intent:")
        print("-"*40)
        for intent_name, data in calibration.items():
            print(f"\n{intent_name}:")
            print(f"  Samples: {data.get('sample_count', 0)}")
            print(f"  Avg success rate: {data.get('avg_success_rate', 0):.0%}")


def _print_intent_stats(intent_name, data):
    """Print detailed stats for an intent."""
    print(f"\nStatistics for: {intent_name}")
    print("="*60)
    print(f"Total samples: {data.get('sample_count', 0)}")
    print(f"Avg success rate: {data.get('avg_success_rate', 0):.0%}")
    print(f"Last updated: {data.get('last_updated', 'N/A')}")

    fields = data.get('fields', {})
    if fields:
        print("\nPer-field statistics:")
        print("-"*60)
        print(f"{'Field':<20} {'Success':<10} {'DOM':<8} {'Browser':<8} {'Vision':<8}")
        print("-"*60)

        for field_name, field_data in fields.items():
            sample_count = field_data.get('sample_count', 0)
            success_count = field_data.get('success_count', 0)
            success_rate = success_count / sample_count if sample_count > 0 else 0

            tiers = field_data.get('tier_counts', {})
            dom = tiers.get('dom', 0)
            browser = tiers.get('browser', 0)
            vision = tiers.get('vision', 0)

            print(f"{field_name:<20} {success_rate:>6.0%}    {dom:>6}  {browser:>6}  {vision:>6}")


def _print_template_results(intent, result, provenance):
    """Print extraction results showing all template fields and their status."""
    print("\n" + "="*70)
    print(f"EXTRACTION RESULTS - Template: {intent.name}")
    print("="*70)
    print(f"{'Field':<20} {'Req':<4} {'Status':<12} {'Tier':<8} {'Conf':<6} Value")
    print("-"*70)

    extracted_count = 0
    required_count = 0
    required_extracted = 0

    for field_def in intent.fields:
        field_name = field_def.name
        required = field_def.required
        if required:
            required_count += 1

        # Get provenance info for this field
        field_prov = provenance.fields.get(field_name)
        value = result.get(field_name)

        if field_prov and field_prov.was_found:
            status = "FOUND"
            tier = field_prov.tier.upper()
            conf = f"{field_prov.confidence:.0%}"
            extracted_count += 1
            if required:
                required_extracted += 1
        else:
            status = "MISSING"
            tier = "-"
            conf = "-"

        req_mark = "*" if required else ""
        value_str = _format_value(value)

        # Truncate value for display
        max_val_len = 25
        if len(value_str) > max_val_len:
            value_str = value_str[:max_val_len-3] + "..."

        print(f"{field_name:<20} {req_mark:<4} {status:<12} {tier:<8} {conf:<6} {value_str}")

    # Summary
    print("-"*70)
    total_fields = len(intent.fields)
    print(f"\nSummary:")
    print(f"  Total fields:    {extracted_count}/{total_fields} extracted ({extracted_count/total_fields:.0%})")
    print(f"  Required fields: {required_extracted}/{required_count} extracted ({required_extracted/required_count:.0%})" if required_count > 0 else "")

    print(f"\n  Tiers used: {' -> '.join(provenance.tier_progression)}")
    print(f"  Total cost: ${provenance.total_cost:.4f}")

    # Show extracted values in detail
    print("\n" + "-"*70)
    print("EXTRACTED VALUES:")
    print("-"*70)
    for field_def in intent.fields:
        field_name = field_def.name
        value = result.get(field_name)
        field_prov = provenance.fields.get(field_name)

        if field_prov and field_prov.was_found and value is not None:
            print(f"\n{field_name}:")
            if isinstance(value, list):
                for i, item in enumerate(value[:10]):  # Limit to 10 items
                    if isinstance(item, dict):
                        print(f"  [{i+1}] {item}")
                    else:
                        print(f"  - {item}")
                if len(value) > 10:
                    print(f"  ... and {len(value) - 10} more")
            elif isinstance(value, dict):
                for k, v in list(value.items())[:10]:
                    print(f"  {k}: {v}")
            else:
                print(f"  {value}")


def _format_value(value):
    """Format a value for display."""
    if value is None:
        return "(not found)"
    if isinstance(value, list):
        if len(value) == 0:
            return "[]"
        if len(value) <= 3:
            return str(value)
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    if isinstance(value, str) and len(value) > 60:
        return value[:57] + "..."
    return str(value)


def main():
    parser = argparse.ArgumentParser(
        description="Extraction Cascade - Cost-optimized web data extraction"
    )
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract data from a URL')
    extract_parser.add_argument('url', nargs='+', help='URL(s) to extract from')
    extract_parser.add_argument('--intent', '-i', default='company_website',
                               help='Extraction template to use (default: company_website)')
    extract_parser.add_argument('--output', '-o', help='Output file (JSON)')
    extract_parser.add_argument('--auto', action='store_true',
                               help='Auto-approve vision requests (no prompts)')
    extract_parser.add_argument('--max-cost', type=float, default=0.10,
                               help='Max cost for auto-approval (default: $0.10)')
    extract_parser.add_argument('--no-browser', action='store_true',
                               help='Skip browser agent tier')
    extract_parser.add_argument('--no-vision', action='store_true',
                               help='Skip vision tier')
    extract_parser.add_argument('--no-provenance', action='store_true',
                               help='Do not save provenance record')
    extract_parser.add_argument('--save-screenshots', action='store_true',
                               help='Save screenshots to disk for review')
    extract_parser.add_argument('--verbose', '-v', action='store_true',
                               help='Show detailed progress (site mapping, crawling, field extraction)')
    extract_parser.add_argument('--all-tiers', action='store_true',
                               help='Run all tiers even if required fields are found early')

    # List templates command
    list_parser = subparsers.add_parser('list-templates', help='List available templates')

    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show extraction statistics')
    stats_parser.add_argument('--intent', '-i', help='Show stats for specific intent')

    args = parser.parse_args()

    if args.command == 'extract':
        cmd_extract(args)
    elif args.command == 'list-templates':
        cmd_list_templates(args)
    elif args.command == 'stats':
        cmd_stats(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
