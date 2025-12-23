from .base import BaseEnricher
from .linkedin import LinkedInEnricher

# VisionEnricher requires vision_extractor package
try:
    from .vision import VisionEnricher
    __all__ = ["BaseEnricher", "LinkedInEnricher", "VisionEnricher"]
except ImportError:
    __all__ = ["BaseEnricher", "LinkedInEnricher"]
