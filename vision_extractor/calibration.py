"""
Calibration loop for refining extraction templates.

Runs extraction on sample URLs, collects feedback, and refines the template.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime

from .intent import ExtractionIntent, ExtractionResult
from .sample_selector import SampleSet
from .core import VisionExtractor
from .template_builder import TemplateBuilder
from .storage import TemplateStorage


@dataclass
class CalibrationMetrics:
    """Metrics from a calibration iteration."""
    samples_processed: int = 0
    samples_successful: int = 0
    fields_extracted: Dict[str, int] = field(default_factory=dict)  # field -> count
    fields_missing: Dict[str, int] = field(default_factory=dict)    # field -> count
    avg_confidence: float = 0.0
    errors: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.samples_processed == 0:
            return 0.0
        return self.samples_successful / self.samples_processed

    def to_dict(self) -> Dict:
        return {
            "samples_processed": self.samples_processed,
            "samples_successful": self.samples_successful,
            "success_rate": self.success_rate,
            "fields_extracted": self.fields_extracted,
            "fields_missing": self.fields_missing,
            "avg_confidence": self.avg_confidence,
            "errors": self.errors
        }


@dataclass
class CalibrationResult:
    """Result of a calibration iteration."""
    iteration: int
    intent: ExtractionIntent
    metrics: CalibrationMetrics
    sample_results: List[ExtractionResult]
    feedback_applied: Optional[str] = None

    @property
    def is_satisfactory(self) -> bool:
        """Check if calibration results are good enough."""
        return self.metrics.success_rate >= 0.8 and self.metrics.avg_confidence >= 0.7


class CalibrationLoop:
    """
    Interactive calibration loop for refining extraction templates.

    Workflow:
    1. Run extraction on sample URLs
    2. Collect accuracy metrics
    3. Present results for review
    4. Apply feedback to refine template
    5. Repeat until satisfactory
    """

    def __init__(
        self,
        intent: ExtractionIntent,
        samples: SampleSet,
        extractor_factory: Callable[[ExtractionIntent], VisionExtractor],
        template_builder: Optional[TemplateBuilder] = None
    ):
        """
        Initialize calibration loop.

        Args:
            intent: Initial ExtractionIntent to calibrate
            samples: SampleSet of URLs to use for calibration
            extractor_factory: Function to create VisionExtractor from intent
            template_builder: Optional TemplateBuilder for refinement
        """
        self.intent = intent
        self.samples = samples
        self.extractor_factory = extractor_factory
        self.template_builder = template_builder or TemplateBuilder()
        self.iteration = 0
        self.history: List[CalibrationResult] = []

    def run_iteration(
        self,
        page_factory: Callable[[str], Any],
        delay_fn: Optional[Callable[[float, float], None]] = None
    ) -> CalibrationResult:
        """
        Run one calibration iteration.

        Args:
            page_factory: Function that takes URL and returns Playwright page
            delay_fn: Optional delay function

        Returns:
            CalibrationResult with metrics and sample results
        """
        self.iteration += 1
        extractor = self.extractor_factory(self.intent)

        metrics = CalibrationMetrics()
        sample_results = []

        total_confidence = 0.0

        for url in self.samples:
            try:
                # Get page for URL
                page = page_factory(url)

                # Run extraction
                result = extractor.extract_and_validate(page, delay_fn=delay_fn)
                sample_results.append(result)

                metrics.samples_processed += 1
                if result.success:
                    metrics.samples_successful += 1

                total_confidence += result.confidence

                # Track field extraction
                for field_def in self.intent.fields:
                    field_name = field_def.name
                    value = result.data.get(field_name)

                    if value and (not isinstance(value, (list, str)) or len(value) > 0):
                        metrics.fields_extracted[field_name] = \
                            metrics.fields_extracted.get(field_name, 0) + 1
                    else:
                        metrics.fields_missing[field_name] = \
                            metrics.fields_missing.get(field_name, 0) + 1

                if result.errors:
                    metrics.errors.extend(result.errors)

            except Exception as e:
                metrics.samples_processed += 1
                metrics.errors.append(f"{url}: {str(e)}")

        # Calculate average confidence
        if metrics.samples_processed > 0:
            metrics.avg_confidence = total_confidence / metrics.samples_processed

        result = CalibrationResult(
            iteration=self.iteration,
            intent=self.intent,
            metrics=metrics,
            sample_results=sample_results
        )

        self.history.append(result)
        return result

    def apply_feedback(self, feedback: str) -> ExtractionIntent:
        """
        Apply user feedback to refine the intent.

        Args:
            feedback: User feedback text

        Returns:
            Updated ExtractionIntent
        """
        self.intent = self.template_builder.refine_with_feedback(self.intent, feedback)

        # Update the last result with feedback
        if self.history:
            self.history[-1].feedback_applied = feedback

        return self.intent

    def finalize(self) -> ExtractionIntent:
        """
        Finalize calibration and return the calibrated intent.

        Updates confidence score and calibration metadata.

        Returns:
            Finalized ExtractionIntent
        """
        if self.history:
            last_result = self.history[-1]
            self.intent.confidence_score = last_result.metrics.avg_confidence
            self.intent.calibrated_from = list(self.samples.urls)

        return self.intent

    def save_template(self, storage: Optional[TemplateStorage] = None) -> str:
        """
        Save the calibrated template.

        Args:
            storage: Optional TemplateStorage instance

        Returns:
            Path to saved template
        """
        storage = storage or TemplateStorage()
        self.finalize()
        return storage.save(self.intent)

    def get_summary(self) -> Dict:
        """Get summary of all calibration iterations."""
        return {
            "total_iterations": self.iteration,
            "current_confidence": self.intent.confidence_score,
            "samples_used": len(self.samples),
            "history": [
                {
                    "iteration": r.iteration,
                    "success_rate": r.metrics.success_rate,
                    "avg_confidence": r.metrics.avg_confidence,
                    "feedback": r.feedback_applied
                }
                for r in self.history
            ]
        }


def run_calibration_cli(
    intent: ExtractionIntent,
    urls: List[str],
    page_factory: Callable[[str], Any],
    n_samples: int = 3,
    max_iterations: int = 5
) -> ExtractionIntent:
    """
    Run calibration with CLI interaction.

    Args:
        intent: Initial ExtractionIntent
        urls: URLs to sample from
        page_factory: Function to get Playwright page for URL
        n_samples: Number of samples per iteration
        max_iterations: Maximum iterations before stopping

    Returns:
        Calibrated ExtractionIntent
    """
    from .sample_selector import SampleSelector

    selector = SampleSelector(urls)
    samples = selector.random_sample(n_samples)

    def extractor_factory(i: ExtractionIntent) -> VisionExtractor:
        return VisionExtractor(i)

    loop = CalibrationLoop(intent, samples, extractor_factory)

    for i in range(max_iterations):
        print(f"\n{'='*60}")
        print(f"CALIBRATION ITERATION {i + 1}")
        print(f"{'='*60}")

        result = loop.run_iteration(page_factory)

        # Display results
        print(f"\nResults:")
        print(f"  Samples processed: {result.metrics.samples_processed}")
        print(f"  Success rate: {result.metrics.success_rate:.0%}")
        print(f"  Avg confidence: {result.metrics.avg_confidence:.2f}")

        print(f"\nFields extracted:")
        for field, count in result.metrics.fields_extracted.items():
            print(f"  {field}: {count}/{result.metrics.samples_processed}")

        if result.metrics.fields_missing:
            print(f"\nFields missing:")
            for field, count in result.metrics.fields_missing.items():
                print(f"  {field}: {count} samples")

        if result.is_satisfactory:
            print(f"\nCalibration satisfactory!")
            confirm = input("Finalize? [Y/n]: ").strip().lower()
            if confirm != 'n':
                break

        # Get feedback
        feedback = input("\nFeedback (or 'done' to finish): ").strip()
        if feedback.lower() == 'done':
            break

        if feedback:
            loop.apply_feedback(feedback)
            print("Feedback applied, running next iteration...")

    return loop.finalize()
