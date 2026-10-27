"""File repositories and path generators.

Importing ``repos`` registers every repository and path generator in the shared ``racker``
registry, so a repository can be built from a configuration dictionary::

    racker.instantiate_from_dict(
        base_class=RepositoryAbstract,
        config_dict={
            "type": "local",
            "base_url": "/tiles/storage",
            "base_root": "/data",
            "path_generator": {"type": "fixed"},
        },
    )
"""

from cragradar_backend.repos import local, path

__all__ = ["local", "path"]
