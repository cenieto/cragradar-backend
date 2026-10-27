"""Pydantic validation that builds registered objects from configuration dictionaries."""

from typing import Annotated, Any, get_origin

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

from cragradar_backend.racker.registry import BaseT, Registry, racker


class Registered:
    """``Annotated`` marker that builds the annotated base class from configuration dictionaries.

    The annotated type is the base class. A dictionary value is turned into an object
    with ``registry.instantiate_from_dict(base_class, value)``. Any other value must
    already be an instance of the base class. Declare a generic alias once per registry
    so that every field names its base class and type checkers see that class::

        Built = Annotated[BaseT, Registered(registry)]

        class AppConfig(BaseModel):
            storage: Built[Storage]
            backup_storage: Built[Storage] | None = None
            mirrors: list[Built[Storage]] = []

    The registry is read at validation time, so classes can be registered after the
    models that use them are defined.

    Attributes:
        registry: Registry holding the classes the fields are built from.
    """

    def __init__(
        self,
        registry: Registry,
    ) -> None:
        """Create the marker.

        Args:
            registry: Registry holding the classes the fields are built from.
        """
        self.registry: Registry = registry

    def __get_pydantic_core_schema__(
        self,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        """Build the pydantic schema of a field annotated with this marker.

        Args:
            source_type: Annotated type, used as the base class.
            handler: Pydantic schema handler, unused because the schema is built here.

        Returns:
            core_schema.CoreSchema: Schema that builds dictionaries into objects and then
                checks that the value is an instance of the base class.

        Raises:
            TypeError: If the annotated type is not a class.
        """
        is_class_annotation: bool = get_origin(source_type) is None and isinstance(
            source_type, type
        )
        if not is_class_annotation:
            raise TypeError(f"Registered can only annotate a class, not {source_type!r}")
        base_class: type = source_type

        def instantiate_from_value(
            value: Any,
        ) -> Any:
            """Build the object of a field from its configuration dictionary.

            Args:
                value: Raw value of the field.

            Returns:
                Any: The built object for a dictionary value, otherwise ``value`` unchanged.

            Raises:
                ValueError: If the base class has no registry, or the dictionary cannot be
                    turned into a registered object.
            """
            is_config_dict: bool = isinstance(value, dict)
            if not is_config_dict:
                return value

            is_base_class_registered: bool = self.registry.is_base_class_registered(
                base_class=base_class,
            )
            if not is_base_class_registered:
                raise ValueError(f"No registry for {base_class}")
            return self.registry.instantiate_from_dict(
                base_class=base_class,
                config_dict=value,
            )

        return core_schema.no_info_before_validator_function(
            instantiate_from_value,
            core_schema.is_instance_schema(base_class),
        )


registrator: Registered = Registered(
    registry=racker,
)

Built = Annotated[BaseT, registrator]
"""Field type built from configuration dictionaries by the shared ``racker`` registry.

Use it as ``Built[BaseClass]``; type checkers see the field as ``BaseClass``.
"""
