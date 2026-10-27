"""Unit tests for the ``Registered`` marker."""

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from cragradar_backend.racker.registry import BaseT, Registry
from cragradar_backend.racker.validators import Registered


class Storage:
    """Base class of the storages built by the registry."""


class LocalStorageConfig(BaseModel):
    """Config of ``LocalStorage``."""

    type: str = "local"
    root: str


class LocalStorage(Storage):
    """Storage built from a ``LocalStorageConfig``."""

    def __init__(self, config: LocalStorageConfig) -> None:
        """Store the config the storage is built with."""
        self.config: LocalStorageConfig = config


class Notifier:
    """Base class of the notifiers built by the registry."""


class EmailNotifierConfig(BaseModel):
    """Config of ``EmailNotifier``."""

    type: str = "email"
    address: str


class EmailNotifier(Notifier):
    """Notifier built from an ``EmailNotifierConfig``."""

    def __init__(self, config: EmailNotifierConfig) -> None:
        """Store the config the notifier is built with."""
        self.config: EmailNotifierConfig = config


class UnregisteredBase:
    """Base class never added to the registry."""


@pytest.fixture
def registry() -> Registry:
    """Build a registry with one storage and one notifier class."""
    registry: Registry = Registry()
    registry.add_base(base_class=Storage)
    registry.add_base(base_class=Notifier)
    registry.register(class_=LocalStorage, config_class=LocalStorageConfig, base_class=Storage)
    registry.register(class_=EmailNotifier, config_class=EmailNotifierConfig, base_class=Notifier)
    return registry


@pytest.fixture
def valid_app_config_data() -> dict[str, Any]:
    """Build raw data whose registry fields are configuration dictionaries."""
    return {
        "storage": {"type": "local", "root": "/data"},
        "notifier": {"type": "email", "address": "team@example.com"},
    }


# --------------------------------------------------------------------------- #
# Registered
# --------------------------------------------------------------------------- #


@pytest.fixture
def registered_app_config_class(registry: Registry) -> type[BaseModel]:
    """Build a model whose fields use a generic ``Registered`` alias."""
    Built = Annotated[BaseT, Registered(registry=registry)]

    class RegisteredAppConfig(BaseModel):
        """Model with required, optional, list and differently based registered fields."""

        storage: Built[Storage]
        backup_storage: Built[Storage] | None = None
        mirror_storages: list[Built[Storage]] = []
        notifier: Built[Notifier]

    return RegisteredAppConfig


def test_registered_builds_objects_of_the_annotated_base_class(
    registered_app_config_class: type[BaseModel],
    valid_app_config_data: dict[str, Any],
) -> None:
    """Check that each field is built from the registry of its own annotated base class."""
    app_config: Any = registered_app_config_class.model_validate(valid_app_config_data)

    assert isinstance(app_config.storage, LocalStorage)
    assert app_config.storage.config == LocalStorageConfig(root="/data")
    assert isinstance(app_config.notifier, EmailNotifier)


def test_registered_builds_optional_field_from_dict_and_keeps_none(
    registered_app_config_class: type[BaseModel],
    valid_app_config_data: dict[str, Any],
) -> None:
    """Check that a ``X | None`` field is built from a dictionary and accepts ``None``."""
    built_app_config: Any = registered_app_config_class.model_validate(
        {**valid_app_config_data, "backup_storage": {"type": "local", "root": "/backup"}}
    )
    empty_app_config: Any = registered_app_config_class.model_validate(
        {**valid_app_config_data, "backup_storage": None}
    )

    assert isinstance(built_app_config.backup_storage, LocalStorage)
    assert empty_app_config.backup_storage is None


def test_registered_builds_every_item_of_a_list_field(
    registered_app_config_class: type[BaseModel],
    valid_app_config_data: dict[str, Any],
) -> None:
    """Check that each dictionary in a ``list[X]`` field is built."""
    app_config: Any = registered_app_config_class.model_validate(
        {
            **valid_app_config_data,
            "mirror_storages": [
                {"type": "local", "root": "/mirror_a"},
                {"type": "local", "root": "/mirror_b"},
            ],
        }
    )

    assert [mirror_storage.config.root for mirror_storage in app_config.mirror_storages] == [
        "/mirror_a",
        "/mirror_b",
    ]


def test_registered_keeps_already_built_object(
    registered_app_config_class: type[BaseModel],
    valid_app_config_data: dict[str, Any],
) -> None:
    """Check that an object given instead of a dictionary is kept as is."""
    local_storage: LocalStorage = LocalStorage(config=LocalStorageConfig(root="/data"))

    app_config: Any = registered_app_config_class.model_validate(
        {**valid_app_config_data, "storage": local_storage}
    )

    assert app_config.storage is local_storage


def test_registered_raises_when_value_is_neither_dict_nor_instance(
    registered_app_config_class: type[BaseModel],
    valid_app_config_data: dict[str, Any],
) -> None:
    """Check that a value of another type fails the instance check."""
    with pytest.raises(ValidationError, match=r"storage"):
        registered_app_config_class.model_validate({**valid_app_config_data, "storage": 42})


def test_registered_raises_when_discriminator_is_unknown(
    registered_app_config_class: type[BaseModel],
    valid_app_config_data: dict[str, Any],
) -> None:
    """Check that a dictionary of no registered config class fails validation."""
    with pytest.raises(ValidationError, match=r"storage"):
        registered_app_config_class.model_validate(
            {**valid_app_config_data, "storage": {"type": "unknown"}}
        )


def test_registered_raises_when_config_is_invalid(
    registered_app_config_class: type[BaseModel],
    valid_app_config_data: dict[str, Any],
) -> None:
    """Check that a dictionary missing a required config field fails validation."""
    with pytest.raises(ValidationError, match=r"root"):
        registered_app_config_class.model_validate(
            {**valid_app_config_data, "storage": {"type": "local"}}
        )


def test_registered_raises_when_base_class_has_no_registry(
    registry: Registry,
) -> None:
    """Check that a field whose base class was never added fails validation."""
    unregistered_adapter: TypeAdapter[UnregisteredBase] = TypeAdapter(
        Annotated[UnregisteredBase, Registered(registry=registry)]
    )

    with pytest.raises(ValidationError, match=r"No registry for"):
        unregistered_adapter.validate_python({"type": "anything"})


def test_registered_uses_classes_registered_after_the_model_is_defined() -> None:
    """Check that the registry is read when validating, not when the model is defined."""
    late_registry: Registry = Registry()

    class LateAppConfig(BaseModel):
        """Model defined before its registry has any entries."""

        storage: Annotated[Storage, Registered(registry=late_registry)]

    late_registry.add_base(base_class=Storage)
    late_registry.register(class_=LocalStorage, config_class=LocalStorageConfig, base_class=Storage)

    app_config: LateAppConfig = LateAppConfig.model_validate(
        {"storage": {"type": "local", "root": "/data"}}
    )

    assert isinstance(app_config.storage, LocalStorage)


def test_registered_works_with_type_adapter(
    registry: Registry,
) -> None:
    """Check that the marker also works outside models."""
    storage_adapter: TypeAdapter[Storage] = TypeAdapter(
        Annotated[Storage, Registered(registry=registry)]
    )

    assert isinstance(
        storage_adapter.validate_python({"type": "local", "root": "/data"}), LocalStorage
    )


def test_registered_raises_when_annotated_type_is_not_a_class(
    registry: Registry,
) -> None:
    """Check that annotating a generic alias such as ``list[X]`` is rejected."""
    with pytest.raises(TypeError, match=r"Registered can only annotate a class"):
        TypeAdapter(Annotated[list[Storage], Registered(registry=registry)])
