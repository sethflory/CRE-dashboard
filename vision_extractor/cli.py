"""
CLI commands for vision extraction.

Provides command-line interface for template management and extraction.
"""

import argparse
import sys
import json
from typing import Optional, List

from .intent import ExtractionIntent
from .storage import TemplateStorage, get_builtin_template
from .template_builder import TemplateBuilder
from .sample_selector import SampleSelector, select_samples_interactive


def cmd_list_templates(args):
    """List all available templates."""
    storage = TemplateStorage()
    templates = storage.list_templates()

    print("\n[Templates] Available Templates")
    print("=" * 50)

    # Built-in templates
    print("\nBuilt-in:")
    for name in ["linkedin_profile", "company_website"]:
        intent = get_builtin_template(name)
        if intent:
            print(f"  - {name}")
            print(f"    {intent.description}")
            print(f"    Fields: {len(intent.fields)}")

    # User templates
    if templates:
        print("\nUser Templates:")
        for name in templates:
            info = storage.get_template_info(name)
            if info:
                print(f"  - {name}")
                print(f"    {info.get('description', 'No description')}")
                print(f"    Fields: {info['fields_count']}, Confidence: {info['confidence_score']:.2f}")
    else:
        print("\nNo user templates found.")

    print()


def cmd_show_template(args):
    """Show details of a specific template."""
    storage = TemplateStorage()

    # Try user template first, then built-in
    intent = storage.load(args.name)
    if not intent:
        intent = get_builtin_template(args.name)

    if not intent:
        print(f"[ERROR] Template '{args.name}' not found")
        return

    print(f"\n[Template] {intent.name}")
    print("=" * 50)
    print(f"Description: {intent.description}")
    print(f"URL Pattern: {intent.target_url_pattern}")
    print(f"Confidence: {intent.confidence_score:.2f}")
    print(f"Batch Threshold: {intent.batch_extraction_threshold}")

    print(f"\n[Scroll Positions] ({len(intent.scroll_positions)}):")
    for sp in intent.scroll_positions:
        print(f"  - {sp.name}: y={sp.y_offset}, wait={sp.wait_ms}ms")

    print(f"\n[Fields] ({len(intent.fields)}):")
    for f in intent.fields:
        type_str = f.type.value
        if f.nested_fields:
            nested = ", ".join(nf.name for nf in f.nested_fields)
            type_str = f"list[{nested}]"
        req = "" if f.required else " (optional)"
        print(f"  - {f.name}: {type_str}{req}")
        if f.description:
            print(f"    > {f.description}")

    if intent.calibrated_from:
        print(f"\n[Calibration] Calibrated from {len(intent.calibrated_from)} URLs")

    if args.json:
        print(f"\n[JSON]:")
        print(json.dumps(intent.to_dict(), indent=2))

    print()


def cmd_create_template(args):
    """Create a new template from description."""
    print("\n[Create] New Template")
    print("=" * 50)

    if args.description:
        description = args.description
    else:
        print("Describe what you want to extract:")
        description = input("> ").strip()

    if not description:
        print("[ERROR] Description required")
        return

    name = args.name or input("Template name: ").strip() or "custom"
    url_pattern = args.pattern or input("URL pattern (optional): ").strip()

    print(f"\n[...] Generating template...")

    try:
        builder = TemplateBuilder()
        intent = builder.from_natural_language(
            description=description,
            template_name=name,
            url_pattern=url_pattern
        )

        print(f"\n[OK] Generated template with {len(intent.fields)} fields:")
        for f in intent.fields:
            print(f"  - {f.name} ({f.type.value})")

        # Confirm save
        if not args.no_save:
            confirm = input("\nSave template? [Y/n]: ").strip().lower()
            if confirm != 'n':
                storage = TemplateStorage()
                path = storage.save(intent)
                print(f"[OK] Saved to: {path}")

    except Exception as e:
        print(f"[ERROR] {e}")


def cmd_save_builtin(args):
    """Save a built-in template to disk for customization."""
    intent = get_builtin_template(args.name)
    if not intent:
        print(f"[ERROR] Built-in template '{args.name}' not found")
        print("Available: linkedin_profile, company_website")
        return

    storage = TemplateStorage()
    path = storage.save(intent)
    print(f"[OK] Saved built-in template to: {path}")
    print("You can now customize this template.")


def cmd_wizard(args):
    """Run the guided extraction wizard."""
    print("\n" + "=" * 70)
    print("  VISION EXTRACTOR WIZARD")
    print("  From Company List → Relationship Network")
    print("=" * 70)

    # Load URLs
    if args.companies:
        with open(args.companies, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        print(f"\nLoaded {len(urls)} companies from {args.companies}")
    else:
        print("\nEnter company URLs (one per line, empty line to finish):")
        urls = []
        while True:
            line = input().strip()
            if not line:
                break
            urls.append(line)

    if not urls:
        print("[ERROR] No URLs provided")
        return

    # Step 1: Sample selection
    print("\n" + "-" * 50)
    print("STEP 1: COMPANY SAMPLES")
    print("-" * 50)
    print(f"\nSelect {args.samples} representative samples for training:")
    print("  [1] Random selection (recommended)")
    print("  [2] Manual selection")
    print("  [3] Stratified by domain")

    choice = input("\nChoice: ").strip() or "1"

    selector = SampleSelector(urls)
    if choice == "1":
        samples = selector.random_sample(args.samples)
    elif choice == "3":
        samples = selector.stratified_sample(args.samples)
    else:
        samples = select_samples_interactive(urls, args.samples, "manual")

    print("\nSelected samples:")
    for url in samples:
        print(f"  - {url}")

    # Step 2: Intent definition
    print("\n" + "-" * 50)
    print("STEP 2: EXTRACTION INTENT")
    print("-" * 50)
    print("\nDescribe what you want to extract from company websites:")

    if args.intent:
        description = args.intent
        print(f"> {description}")
    else:
        description = input("> ").strip()

    if not description:
        # Use default
        description = "Extract company name, headquarters, services/lines of business, asset class specialties, and leadership team with titles"
        print(f"Using default: {description}")

    # Generate template
    print("\n[...] Generating extraction template...")

    try:
        builder = TemplateBuilder()
        intent = builder.from_natural_language(
            description=description,
            template_name="company_website",
            url_pattern=r".*"
        )

        print(f"\n[OK] Generated fields:")
        for f in intent.fields:
            print(f"  [+] {f.name} ({f.type.value})")

        adjust = input("\nAdjust? [y/N]: ").strip().lower()
        if adjust == 'y':
            feedback = input("Describe changes: ").strip()
            if feedback:
                intent = builder.refine_with_feedback(intent, feedback)
                print("Template updated.")

    except Exception as e:
        print(f"[ERROR] Error generating template: {e}")
        print("Using built-in company_website template.")
        intent = get_builtin_template("company_website")

    # Save template
    storage = TemplateStorage()
    storage.save(intent)

    print("\n" + "-" * 50)
    print("WIZARD SETUP COMPLETE")
    print("-" * 50)
    print(f"\n[OK] Template saved: {intent.name}")
    print(f"[OK] {len(samples)} samples selected for calibration")
    print("\nTo continue with calibration and extraction, use:")
    print(f"  python -m vision_extractor calibrate --template {intent.name}")


def cmd_calibrate(args):
    """Run calibration on sample URLs."""
    print("\n[Calibrate] Running calibration")
    print("=" * 50)

    # Load template
    storage = TemplateStorage()
    intent = storage.load(args.template)
    if not intent:
        intent = get_builtin_template(args.template)
    if not intent:
        print(f"[ERROR] Template '{args.template}' not found")
        return

    print(f"Template: {intent.name}")

    # Load URLs
    try:
        with open(args.urls, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        print(f"[ERROR] URL file not found: {args.urls}")
        return

    print(f"URLs loaded: {len(urls)}")

    # Select samples
    selector = SampleSelector(urls)
    samples = selector.random_sample(args.samples)

    print(f"\nSelected {len(samples)} samples:")
    for url in samples:
        print(f"  - {url}")

    print("\n[INFO] Calibration requires browser automation.")
    print("This will:")
    print("  1. Open each sample URL in a browser")
    print("  2. Capture screenshots at configured scroll positions")
    print("  3. Extract data and validate against screenshots")
    print("  4. Report accuracy metrics")

    proceed = input("\nProceed? [Y/n]: ").strip().lower()
    if proceed == 'n':
        print("Calibration cancelled.")
        return

    # Run calibration (simplified - full version needs Playwright)
    print("\n[...] Starting calibration...")
    print("\nNote: Full calibration requires Playwright browser automation.")
    print("Install with: pip install playwright && python -m playwright install chromium")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})

            from .core import VisionExtractor
            extractor = VisionExtractor(intent, save_debug_screenshots=True)

            results = []
            for i, url in enumerate(samples, 1):
                print(f"\n[{i}/{len(samples)}] Processing: {url}")
                try:
                    page.goto(url, timeout=30000)
                    page.wait_for_load_state('networkidle', timeout=10000)

                    # Capture and extract
                    result = extractor.extract_and_validate(page)
                    results.append(result)

                    print(f"  Confidence: {result.confidence:.2f}")
                    print(f"  Mode: {result.extraction_mode}")
                    if result.data:
                        for key, val in list(result.data.items())[:5]:
                            val_str = str(val)[:50] + "..." if len(str(val)) > 50 else str(val)
                            print(f"  {key}: {val_str}")

                except Exception as e:
                    print(f"  [ERROR] {e}")

            browser.close()

            # Summary
            print("\n" + "=" * 50)
            print("CALIBRATION SUMMARY")
            print("=" * 50)
            successful = [r for r in results if r.success]
            print(f"Samples processed: {len(results)}")
            print(f"Successful: {len(successful)}")
            if results:
                avg_conf = sum(r.confidence for r in results) / len(results)
                print(f"Average confidence: {avg_conf:.2f}")

    except ImportError:
        print("\n[ERROR] Playwright not installed.")
        print("Install with: pip install playwright && python -m playwright install chromium")


def cmd_extract(args):
    """Extract from a single URL."""
    print("\n[Extract] Single URL extraction")
    print("=" * 50)

    # Load template
    storage = TemplateStorage()
    intent = storage.load(args.template)
    if not intent:
        intent = get_builtin_template(args.template)
    if not intent:
        print(f"[ERROR] Template '{args.template}' not found")
        return

    print(f"Template: {intent.name}")
    print(f"URL: {args.url}")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})

            print("\n[...] Loading page...")
            page.goto(args.url, timeout=30000)
            page.wait_for_load_state('networkidle', timeout=10000)

            from .core import VisionExtractor
            extractor = VisionExtractor(intent, save_debug_screenshots=True)

            print("[...] Extracting...")
            result = extractor.extract_and_validate(page)

            browser.close()

            print(f"\n[OK] Extraction complete")
            print(f"Confidence: {result.confidence:.2f}")
            print(f"Mode: {result.extraction_mode}")

            print("\nExtracted data:")
            print(json.dumps(result.data, indent=2, default=str))

            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(result.data, f, indent=2, default=str)
                print(f"\n[OK] Saved to: {args.output}")

    except ImportError:
        print("\n[ERROR] Playwright not installed.")
        print("Install with: pip install playwright && python -m playwright install chromium")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Vision Extractor - Hybrid Claude vision extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all templates
  python -m vision_extractor list

  # Show template details
  python -m vision_extractor show linkedin_profile

  # Create new template from description
  python -m vision_extractor create --name my_template --description "Extract name, title, company"

  # Run guided wizard
  python -m vision_extractor wizard --companies urls.txt

  # Save built-in template for customization
  python -m vision_extractor save-builtin linkedin_profile
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # list command
    list_parser = subparsers.add_parser("list", help="List available templates")
    list_parser.set_defaults(func=cmd_list_templates)

    # show command
    show_parser = subparsers.add_parser("show", help="Show template details")
    show_parser.add_argument("name", help="Template name")
    show_parser.add_argument("--json", action="store_true", help="Output as JSON")
    show_parser.set_defaults(func=cmd_show_template)

    # create command
    create_parser = subparsers.add_parser("create", help="Create new template")
    create_parser.add_argument("--name", help="Template name")
    create_parser.add_argument("--description", "-d", help="Extraction description")
    create_parser.add_argument("--pattern", "-p", help="URL pattern regex")
    create_parser.add_argument("--no-save", action="store_true", help="Don't save to disk")
    create_parser.set_defaults(func=cmd_create_template)

    # save-builtin command
    save_parser = subparsers.add_parser("save-builtin", help="Save built-in template for customization")
    save_parser.add_argument("name", help="Built-in template name")
    save_parser.set_defaults(func=cmd_save_builtin)

    # wizard command
    wizard_parser = subparsers.add_parser("wizard", help="Run guided extraction wizard")
    wizard_parser.add_argument("--companies", "-c", help="File with company URLs")
    wizard_parser.add_argument("--samples", "-n", type=int, default=3, help="Number of samples")
    wizard_parser.add_argument("--intent", "-i", help="Extraction intent description")
    wizard_parser.set_defaults(func=cmd_wizard)

    # calibrate command
    calibrate_parser = subparsers.add_parser("calibrate", help="Run calibration on sample URLs")
    calibrate_parser.add_argument("--template", "-t", required=True, help="Template name")
    calibrate_parser.add_argument("--urls", "-u", required=True, help="File with URLs to calibrate on")
    calibrate_parser.add_argument("--samples", "-n", type=int, default=3, help="Number of samples per iteration")
    calibrate_parser.add_argument("--max-iterations", type=int, default=5, help="Maximum calibration iterations")
    calibrate_parser.set_defaults(func=cmd_calibrate)

    # extract command
    extract_parser = subparsers.add_parser("extract", help="Extract from a single URL")
    extract_parser.add_argument("--template", "-t", required=True, help="Template name")
    extract_parser.add_argument("--url", required=True, help="URL to extract from")
    extract_parser.add_argument("--output", "-o", help="Output JSON file")
    extract_parser.set_defaults(func=cmd_extract)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
