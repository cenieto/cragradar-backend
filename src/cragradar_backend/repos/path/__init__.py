"""Path generators, registered in ``racker`` under ``PathGeneratorAbstract`` when imported."""

from cragradar_backend.repos.path.date import DatePathGenerator, DatePathGeneratorConfig
from cragradar_backend.repos.path.fixed import FixedPathGenerator, FixedPathGeneratorConfig

__all__ = [
    "DatePathGenerator",
    "DatePathGeneratorConfig",
    "FixedPathGenerator",
    "FixedPathGeneratorConfig",
]
