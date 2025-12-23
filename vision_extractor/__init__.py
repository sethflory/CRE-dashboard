"""
Vision Extractor - Reusable hybrid Claude vision extraction component.

This package provides a generalized pattern for extracting data from webpages
using a combination of DOM parsing and Claude vision API validation/correction.

Key Components:
- ExtractionIntent: Schema defining what to extract
- VisionExtractor: Main extraction class with hybrid workflow
- TemplateBuilder: Create templates from natural language
- TemplateStorage: Save/load templates as JSON
- CalibrationLoop: Refine templates with sample data

Basic Usage:
    from vision_extractor import VisionExtractor, TemplateStorage

    # Load a template
    storage = TemplateStorage()
    intent = storage.load("linkedin_profile")

    # Create extractor
    extractor = VisionExtractor(intent, claude_api_key="...")

    # Extract with validation
    result = extractor.extract_and_validate(page)

Template Creation:
    from vision_extractor import TemplateBuilder

    builder = TemplateBuilder(api_key="...")
    intent = builder.from_natural_language(
        "Extract person's name, title, company, and work history",
        template_name="my_template"
    )

Calibration:
    from vision_extractor import CalibrationLoop, SampleSelector

    selector = SampleSelector(urls)
    samples = selector.random_sample(3)

    loop = CalibrationLoop(intent, samples, extractor_factory)
    result = loop.run_iteration(page_factory)

CLI:
    python -m vision_extractor list
    python -m vision_extractor show linkedin_profile
    python -m vision_extractor wizard --companies urls.txt
"""

from .intent import (
    ExtractionIntent,
    ExtractionResult,
    FieldDefinition,
    FieldType,
    ScrollPosition,
    ValidationResult,
    AttributeLinking,
)

from .core import (
    VisionExtractor,
    create_extractor_from_template,
)

from .storage import (
    TemplateStorage,
    get_builtin_template,
)

from .template_builder import (
    TemplateBuilder,
    quick_template,
)

from .sample_selector import (
    SampleSelector,
    SampleSet,
    select_samples_interactive,
)

from .calibration import (
    CalibrationLoop,
    CalibrationResult,
    CalibrationMetrics,
    run_calibration_cli,
)

from .screenshot import (
    ScreenshotCapture,
    ScreenshotConfig,
    get_default_linkedin_positions,
    get_default_company_positions,
)

from .validation import (
    ClaudeVisionValidator,
)

__version__ = "0.1.0"

__all__ = [
    # Intent/Schema
    "ExtractionIntent",
    "ExtractionResult",
    "FieldDefinition",
    "FieldType",
    "ScrollPosition",
    "ValidationResult",
    "AttributeLinking",
    # Core
    "VisionExtractor",
    "create_extractor_from_template",
    # Storage
    "TemplateStorage",
    "get_builtin_template",
    # Builder
    "TemplateBuilder",
    "quick_template",
    # Sampling
    "SampleSelector",
    "SampleSet",
    "select_samples_interactive",
    # Calibration
    "CalibrationLoop",
    "CalibrationResult",
    "CalibrationMetrics",
    "run_calibration_cli",
    # Screenshot
    "ScreenshotCapture",
    "ScreenshotConfig",
    "get_default_linkedin_positions",
    "get_default_company_positions",
    # Validation
    "ClaudeVisionValidator",
]
