"""Tilers that cut images into tiles for viewers such as OpenSeadragon.

Importing ``tiler`` registers every tiler in the shared ``racker`` registry, so a tiler can
be built from a configuration dictionary such as ``{"type": "deepzoom", "tile_size": 512}``.
"""

from cragradar_backend.tiler import deepzoom

__all__ = ["deepzoom"]
