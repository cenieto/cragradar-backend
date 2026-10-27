"""Unit tests for the ``Entry`` model and the ``RegistryBase`` and ``Registry`` classes."""

import re

import pytest
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from cragradar_backend.racker.registry import Entry, Registry, RegistryBase


class BaseClass:
    """Base class used as the registry base type."""


class SubClassA(BaseClass):
    """First concrete subclass of ``BaseClass``."""

    def __init__(self, config: "ConfigA") -> None:
        """Store the config the object is built with."""
        self.config: ConfigA = config


class SubClassB(BaseClass):
    """Second concrete subclass of ``BaseClass``."""


class ConfigA(BaseModel):
    """Config of ``SubClassA`` with a discriminator field."""

    type: str = "example_a"
    value: int = 0


class ConfigB(BaseModel):
    """Config of ``SubClassB`` with a discriminator field."""

    type: str = "example_b"


class ConfigReusingDiscriminatorOfA(BaseModel):
    """Config whose discriminator default collides with the one of ``ConfigA``."""

    type: str = "example_a"


class ConfigWithoutDiscriminator(BaseModel):
    """Config that lacks the discriminator field."""


class ConfigWithRequiredDiscriminator(BaseModel):
    """Config whose discriminator field has no default value."""

    type: str


class ConfigWithFactoryDiscriminator(BaseModel):
    """Config whose discriminator default comes from a ``default_factory``."""

    type: str = Field(default_factory=lambda: "example_factory")


class ConfigWithNoneDiscriminator(BaseModel):
    """Config whose discriminator field defaults to ``None``."""

    type: str | None = None


class SubClassC(BaseClass):
    """Third concrete subclass of ``BaseClass``, registered by no fixture."""


class UnrelatedBaseClass:
    """Base class that differs from the registry base type."""


class UnrelatedSubClass(UnrelatedBaseClass):
    """Subclass of ``UnrelatedBaseClass``."""


class SubClassOfBothBases(BaseClass, UnrelatedBaseClass):
    """Subclass of both ``BaseClass`` and ``UnrelatedBaseClass``."""


class ConfigOfBothBasesForBaseClass(BaseModel):
    """Config of ``SubClassOfBothBases`` under ``BaseClass``."""

    type: str = "both_bases_for_base_class"


class ConfigOfBothBasesForUnrelatedBaseClass(BaseModel):
    """Config of ``SubClassOfBothBases`` under ``UnrelatedBaseClass``."""

    type: str = "both_bases_for_unrelated_base_class"


class UnrelatedConfig(BaseModel):
    """Config of ``UnrelatedSubClass`` with a discriminator field."""

    type: str = "unrelated_example"


@pytest.fixture
def entry_for_sub_class_a() -> Entry:
    """Build a valid entry linking ``SubClassA`` and ``ConfigA``."""
    return Entry(base_class=BaseClass, class_=SubClassA, config_class=ConfigA)


@pytest.fixture
def entry_for_sub_class_b() -> Entry:
    """Build a valid entry linking ``SubClassB`` and ``ConfigB``."""
    return Entry(base_class=BaseClass, class_=SubClassB, config_class=ConfigB)


@pytest.fixture
def entry_with_unrelated_base_class() -> Entry:
    """Build a valid entry whose base class differs from the registry's."""
    return Entry(
        base_class=UnrelatedBaseClass,
        class_=UnrelatedSubClass,
        config_class=UnrelatedConfig,
    )


@pytest.fixture
def empty_registry() -> RegistryBase:
    """Build an empty registry for ``BaseClass``."""
    return RegistryBase(base_class=BaseClass)


@pytest.fixture
def registry_with_two_entries(
    empty_registry: RegistryBase,
    entry_for_sub_class_a: Entry,
    entry_for_sub_class_b: Entry,
) -> RegistryBase:
    """Build a registry with the entries for ``SubClassA`` and ``SubClassB``."""
    empty_registry.register(entry=entry_for_sub_class_a)
    empty_registry.register(entry=entry_for_sub_class_b)
    return empty_registry


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #


def test_entry_validate_entry_stores_given_classes_when_entry_is_valid() -> None:
    """Check that a valid entry keeps the base, class and config classes it was given."""
    entry: Entry = Entry(base_class=BaseClass, class_=SubClassA, config_class=ConfigA)

    assert (entry.base_class, entry.class_, entry.config_class) == (
        BaseClass,
        SubClassA,
        ConfigA,
    )


def test_entry_validate_entry_raises_when_class_is_not_subclass_of_base_class() -> None:
    """Check that a class unrelated to the base class is rejected."""
    with pytest.raises(ValueError, match=r"is not a subclass of"):
        Entry(base_class=BaseClass, class_=int, config_class=ConfigA)


def test_entry_validate_entry_raises_when_config_class_has_no_discriminator_field() -> None:
    """Check that a config class without the discriminator field is rejected."""
    expected_message_pattern: str = (
        rf"{re.escape(str(ConfigWithoutDiscriminator))} has no discriminator field: 'type'"
    )

    with pytest.raises(ValueError, match=expected_message_pattern):
        Entry(
            base_class=BaseClass,
            class_=SubClassA,
            config_class=ConfigWithoutDiscriminator,
        )


def test_entry_validate_entry_raises_when_discriminator_field_has_no_default_value() -> None:
    """Check that a discriminator field without a default value is rejected."""
    expected_message_pattern: str = (
        rf"{re.escape(str(ConfigWithRequiredDiscriminator))} discriminator field 'type' "
        "must define a default value"
    )

    with pytest.raises(ValueError, match=expected_message_pattern):
        Entry(
            base_class=BaseClass,
            class_=SubClassA,
            config_class=ConfigWithRequiredDiscriminator,
        )


def test_entry_validate_entry_raises_when_discriminator_default_comes_from_factory() -> None:
    """Check that a discriminator without a static default value is rejected."""
    with pytest.raises(ValueError, match=r"must define a static default value"):
        Entry(
            base_class=BaseClass,
            class_=SubClassA,
            config_class=ConfigWithFactoryDiscriminator,
        )


def test_entry_validate_entry_raises_when_discriminator_defaults_to_none() -> None:
    """Check that a discriminator defaulting to ``None`` is rejected."""
    with pytest.raises(ValueError, match=r"must not default to None"):
        Entry(
            base_class=BaseClass,
            class_=SubClassA,
            config_class=ConfigWithNoneDiscriminator,
        )


def test_entry_discriminator_field_name_is_a_public_class_level_constant() -> None:
    """Check that the discriminator name is readable from the class as a plain string."""
    assert Entry.DISCRIMINATOR_FIELD_NAME == "type"


# --------------------------------------------------------------------------- #
# RegistryBase: properties
# --------------------------------------------------------------------------- #


def test_registry_base_config_classes_returns_registered_config_classes_in_order(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that config classes are returned in registration order."""
    assert registry_with_two_entries.config_classes == [ConfigA, ConfigB]


def test_registry_base_classes_returns_registered_classes_in_order(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that registered classes are returned in registration order."""
    assert registry_with_two_entries.classes_ == [SubClassA, SubClassB]


# --------------------------------------------------------------------------- #
# RegistryBase: is_entry_registered / is_entry_of_base_type
# --------------------------------------------------------------------------- #


def test_registry_base_is_entry_registered_returns_true_when_entry_was_registered(
    registry_with_two_entries: RegistryBase,
    entry_for_sub_class_a: Entry,
) -> None:
    """Check that a registered entry is reported as registered."""
    assert registry_with_two_entries.is_entry_registered(entry=entry_for_sub_class_a)


def test_registry_base_is_entry_registered_returns_false_when_entry_was_not_registered(
    registry_with_two_entries: RegistryBase,
    entry_with_unrelated_base_class: Entry,
) -> None:
    """Check that an unknown entry is reported as not registered."""
    assert not registry_with_two_entries.is_entry_registered(entry=entry_with_unrelated_base_class)


def test_registry_base_is_config_class_registered_tells_registered_from_unknown_config_classes(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that only registered config classes are reported as registered."""
    assert registry_with_two_entries.is_config_class_registered(config_class=ConfigA)
    assert not registry_with_two_entries.is_config_class_registered(config_class=UnrelatedConfig)


def test_registry_base_is_entry_of_base_type_returns_true_when_base_class_matches(
    empty_registry: RegistryBase,
    entry_for_sub_class_a: Entry,
) -> None:
    """Check that an entry sharing the registry base class is accepted."""
    assert empty_registry.is_entry_of_base_type(entry=entry_for_sub_class_a)


def test_registry_base_is_entry_of_base_type_returns_false_when_base_class_differs(
    empty_registry: RegistryBase,
    entry_with_unrelated_base_class: Entry,
) -> None:
    """Check that an entry with a different base class is rejected."""
    assert not empty_registry.is_entry_of_base_type(entry=entry_with_unrelated_base_class)


# --------------------------------------------------------------------------- #
# RegistryBase: register
# --------------------------------------------------------------------------- #


def test_registry_base_register_stores_entry_under_its_config_class(
    empty_registry: RegistryBase,
    entry_for_sub_class_a: Entry,
) -> None:
    """Check that a registered entry can be retrieved by its config class."""
    empty_registry.register(entry=entry_for_sub_class_a)

    assert empty_registry.get_entry_from_config_class(config_class=ConfigA) == entry_for_sub_class_a


def test_registry_base_register_raises_when_entry_is_already_registered(
    registry_with_two_entries: RegistryBase,
    entry_for_sub_class_b: Entry,
) -> None:
    """Check that registering the same entry twice is rejected."""
    with pytest.raises(ValueError, match=r"Entry for .*? already registered"):
        registry_with_two_entries.register(entry=entry_for_sub_class_b)


def test_registry_base_register_raises_when_entry_has_different_base_class(
    empty_registry: RegistryBase,
    entry_with_unrelated_base_class: Entry,
) -> None:
    """Check that an entry of another base class is rejected."""
    with pytest.raises(ValueError, match=r"Entry for .*? is not of base class: "):
        empty_registry.register(entry=entry_with_unrelated_base_class)


def test_registry_base_register_raises_when_config_class_is_registered_for_another_class(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that a config class already used by another class is rejected."""
    entry_reusing_config_class: Entry = Entry(
        base_class=BaseClass,
        class_=SubClassB,
        config_class=ConfigA,
    )

    with pytest.raises(ValueError, match=r"Config class .*? already registered for .*?SubClassA"):
        registry_with_two_entries.register(entry=entry_reusing_config_class)


def test_registry_base_register_raises_when_discriminator_value_is_already_used(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that two config classes cannot share the same discriminator value."""
    entry_reusing_discriminator: Entry = Entry(
        base_class=BaseClass,
        class_=SubClassC,
        config_class=ConfigReusingDiscriminatorOfA,
    )

    with pytest.raises(ValueError, match=r"Discriminator value 'example_a' .*? already used by"):
        registry_with_two_entries.register(entry=entry_reusing_discriminator)


def test_registry_base_register_raises_when_class_is_registered_with_another_config_class(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that a registered class cannot be configured by a second config class."""
    entry_reusing_class: Entry = Entry(
        base_class=BaseClass,
        class_=SubClassA,
        config_class=ConfigReusingDiscriminatorOfA,
    )

    with pytest.raises(
        ValueError, match=r"Class .*?SubClassA.*? already registered with .*?ConfigA"
    ):
        registry_with_two_entries.register(entry=entry_reusing_class)


def test_registry_base_is_class_registered_tells_registered_from_unknown_classes(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that only registered classes are reported as registered."""
    assert registry_with_two_entries.is_class_registered(class_=SubClassA)
    assert not registry_with_two_entries.is_class_registered(class_=SubClassC)


def test_registry_base_register_keeps_original_entry_when_config_class_is_reused(
    registry_with_two_entries: RegistryBase,
    entry_for_sub_class_a: Entry,
) -> None:
    """Check that a rejected duplicate config class does not overwrite the original entry."""
    entry_reusing_config_class: Entry = Entry(
        base_class=BaseClass,
        class_=SubClassB,
        config_class=ConfigA,
    )

    with pytest.raises(ValueError):
        registry_with_two_entries.register(entry=entry_reusing_config_class)

    assert (
        registry_with_two_entries.get_entry_from_config_class(config_class=ConfigA)
        == entry_for_sub_class_a
    )


def test_registry_base_register_leaves_registry_unchanged_when_entry_is_rejected(
    empty_registry: RegistryBase,
    entry_with_unrelated_base_class: Entry,
) -> None:
    """Check that a rejected entry is not stored in the registry."""
    with pytest.raises(ValueError):
        empty_registry.register(entry=entry_with_unrelated_base_class)

    assert empty_registry.config_classes == []


# --------------------------------------------------------------------------- #
# RegistryBase: lookups
# --------------------------------------------------------------------------- #


def test_registry_base_get_entry_from_config_class_returns_matching_entry(
    registry_with_two_entries: RegistryBase,
    entry_for_sub_class_b: Entry,
) -> None:
    """Check that the entry registered for a config class is returned."""
    assert (
        registry_with_two_entries.get_entry_from_config_class(config_class=ConfigB)
        == entry_for_sub_class_b
    )


def test_registry_base_get_entry_from_config_class_returns_none_when_config_class_is_unknown(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that an unregistered config class yields ``None``."""
    assert (
        registry_with_two_entries.get_entry_from_config_class(config_class=UnrelatedConfig) is None
    )


def test_registry_base_get_entry_from_class_returns_matching_entry(
    registry_with_two_entries: RegistryBase,
    entry_for_sub_class_a: Entry,
) -> None:
    """Check that the entry registered for a class is returned."""
    assert registry_with_two_entries.get_entry_from_class(class_=SubClassA) == entry_for_sub_class_a


def test_registry_base_get_entry_from_class_returns_none_when_class_is_unknown(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that an unregistered class yields ``None``."""
    assert registry_with_two_entries.get_entry_from_class(class_=UnrelatedSubClass) is None


# --------------------------------------------------------------------------- #
# RegistryBase: config_type_adapter
# --------------------------------------------------------------------------- #


def test_registry_base_config_type_adapter_validates_dict_into_matching_config_class(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that the discriminator value selects the config class to build."""
    config_type_adapter: TypeAdapter[BaseModel] = registry_with_two_entries.config_type_adapter

    assert config_type_adapter.validate_python({"type": "example_b"}) == ConfigB()
    assert config_type_adapter.validate_python({"type": "example_a", "value": 3}) == ConfigA(
        value=3
    )


def test_registry_base_config_type_adapter_accepts_config_instance(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that an already built config object is validated as itself."""
    config_b: ConfigB = ConfigB()

    assert registry_with_two_entries.config_type_adapter.validate_python(config_b) == config_b


def test_registry_base_config_type_adapter_raises_when_discriminator_value_is_unknown(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that a discriminator value of no registered config class is rejected."""
    with pytest.raises(ValidationError):
        registry_with_two_entries.config_type_adapter.validate_python({"type": "unknown"})


def test_registry_base_config_type_adapter_raises_when_discriminator_is_missing(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that data without the discriminator field is rejected."""
    with pytest.raises(ValidationError):
        registry_with_two_entries.config_type_adapter.validate_python({"value": 3})


def test_registry_base_config_type_adapter_is_reused_between_registrations(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that reading the adapter twice returns the same object."""
    assert (
        registry_with_two_entries.config_type_adapter
        is registry_with_two_entries.config_type_adapter
    )


def test_registry_base_config_type_adapter_is_rebuilt_when_an_entry_is_registered(
    registry_with_two_entries: RegistryBase,
) -> None:
    """Check that registering an entry replaces the adapter with one that knows the new config."""
    adapter_before_register: TypeAdapter[BaseModel] = registry_with_two_entries.config_type_adapter
    registry_with_two_entries.register(
        entry=Entry(
            base_class=BaseClass,
            class_=SubClassOfBothBases,
            config_class=ConfigOfBothBasesForBaseClass,
        )
    )

    adapter_after_register: TypeAdapter[BaseModel] = registry_with_two_entries.config_type_adapter

    assert adapter_after_register is not adapter_before_register
    assert (
        adapter_after_register.validate_python({"type": "both_bases_for_base_class"})
        == ConfigOfBothBasesForBaseClass()
    )


def test_registry_base_config_type_adapter_raises_when_registry_is_empty(
    empty_registry: RegistryBase,
) -> None:
    """Check that an empty registry cannot build a type adapter."""
    with pytest.raises(ValueError, match=r"has no entries"):
        _ = empty_registry.config_type_adapter


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


@pytest.fixture
def empty_multi_registry() -> Registry:
    """Build a ``Registry`` with no base classes."""
    return Registry()


@pytest.fixture
def populated_registry(
    empty_multi_registry: Registry,
    entry_for_sub_class_a: Entry,
    entry_for_sub_class_b: Entry,
    entry_with_unrelated_base_class: Entry,
) -> Registry:
    """Build a ``Registry`` with two base classes and their entries."""
    empty_multi_registry.add_base(base_class=BaseClass)
    empty_multi_registry.add_base(base_class=UnrelatedBaseClass)
    empty_multi_registry.add_entry(entry=entry_for_sub_class_a)
    empty_multi_registry.add_entry(entry=entry_for_sub_class_b)
    empty_multi_registry.add_entry(entry=entry_with_unrelated_base_class)
    return empty_multi_registry


def test_registry_add_base_stores_an_empty_registry_base_for_the_base_class(
    empty_multi_registry: Registry,
) -> None:
    """Check that adding a base class creates one empty registry for it."""
    added_registry_base: RegistryBase[BaseClass] = empty_multi_registry.add_base(
        base_class=BaseClass
    )

    assert empty_multi_registry.is_base_class_registered(base_class=BaseClass)
    assert empty_multi_registry.registry_bases == [added_registry_base]
    assert (added_registry_base.base_class, added_registry_base.config_classes) == (BaseClass, [])


def test_registry_instances_do_not_share_registries(
    populated_registry: Registry,
) -> None:
    """Check that each ``Registry`` instance owns its own registries."""
    assert Registry().registry_bases == []


def test_registry_add_base_raises_when_base_class_is_already_registered(
    empty_multi_registry: Registry,
) -> None:
    """Check that the same base class cannot be added twice."""
    empty_multi_registry.add_base(base_class=BaseClass)

    with pytest.raises(ValueError, match=r"Registry for .*? already registered"):
        empty_multi_registry.add_base(base_class=BaseClass)


def test_registry_add_entry_raises_when_config_class_is_registered_under_another_base_class(
    populated_registry: Registry,
) -> None:
    """Check that a config class cannot belong to two base classes."""
    entry_reusing_config_class_of_other_base: Entry = Entry(
        base_class=UnrelatedBaseClass,
        class_=UnrelatedSubClass,
        config_class=ConfigA,
    )

    with pytest.raises(ValueError, match=r"already registered for .*?SubClassA.*? another base"):
        populated_registry.add_entry(entry=entry_reusing_config_class_of_other_base)

    assert populated_registry.get_class_by_config_class(config_class=ConfigA) is SubClassA


def test_registry_add_entry_raises_when_class_is_registered_under_another_base_class(
    populated_registry: Registry,
) -> None:
    """Check that a class cannot be configured under two base classes."""
    populated_registry.register(
        class_=SubClassOfBothBases,
        config_class=ConfigOfBothBasesForBaseClass,
        base_class=BaseClass,
    )

    with pytest.raises(
        ValueError, match=r"Class .*?SubClassOfBothBases.*? already registered .*? another base"
    ):
        populated_registry.register(
            class_=SubClassOfBothBases,
            config_class=ConfigOfBothBasesForUnrelatedBaseClass,
            base_class=UnrelatedBaseClass,
        )

    assert (
        populated_registry.get_config_class_by_class(class_=SubClassOfBothBases)
        is ConfigOfBothBasesForBaseClass
    )


def test_registry_add_entry_raises_when_base_class_has_no_registry(
    empty_multi_registry: Registry,
    entry_for_sub_class_a: Entry,
) -> None:
    """Check that an entry cannot be added before its base class."""
    with pytest.raises(KeyError, match=r"No registry for"):
        empty_multi_registry.add_entry(entry=entry_for_sub_class_a)


def test_registry_get_class_by_config_class_searches_every_registry(
    populated_registry: Registry,
) -> None:
    """Check that classes are found whichever registry holds them."""
    assert populated_registry.get_class_by_config_class(config_class=ConfigB) is SubClassB
    assert (
        populated_registry.get_class_by_config_class(config_class=UnrelatedConfig)
        is UnrelatedSubClass
    )


def test_registry_get_class_by_config_class_returns_none_when_config_class_is_unknown(
    populated_registry: Registry,
) -> None:
    """Check that an unregistered config class yields ``None``."""
    assert (
        populated_registry.get_class_by_config_class(config_class=ConfigWithoutDiscriminator)
        is None
    )


def test_registry_get_config_class_by_class_searches_every_registry(
    populated_registry: Registry,
) -> None:
    """Check that config classes are found whichever registry holds them."""
    assert populated_registry.get_config_class_by_class(class_=SubClassA) is ConfigA
    assert populated_registry.get_config_class_by_class(class_=UnrelatedSubClass) is UnrelatedConfig


def test_registry_get_config_class_by_class_returns_none_when_class_is_unknown(
    populated_registry: Registry,
) -> None:
    """Check that an unregistered class yields ``None``."""
    assert populated_registry.get_config_class_by_class(class_=int) is None


def test_registry_instantiate_from_dict_builds_class_with_validated_config(
    populated_registry: Registry,
) -> None:
    """Check that the dict selects the class and is passed to it as a config object."""
    built_object: BaseClass = populated_registry.instantiate_from_dict(
        base_class=BaseClass,
        config_dict={"type": "example_a", "value": 7},
    )

    assert isinstance(built_object, SubClassA)
    assert built_object.config == ConfigA(value=7)


def test_registry_instantiate_from_dict_raises_when_base_class_has_no_registry(
    empty_multi_registry: Registry,
) -> None:
    """Check that an unknown base class is rejected."""
    with pytest.raises(KeyError, match=r"No registry for"):
        empty_multi_registry.instantiate_from_dict(base_class=BaseClass, config_dict={})


def test_registry_instantiate_from_dict_raises_when_dict_matches_no_config_class(
    populated_registry: Registry,
) -> None:
    """Check that a config of another base class is not accepted."""
    with pytest.raises(ValidationError):
        populated_registry.instantiate_from_dict(
            base_class=BaseClass,
            config_dict={"type": "unrelated_example"},
        )


def test_registry_register_stores_classes_in_registry_of_base_class(
    empty_multi_registry: Registry,
) -> None:
    """Check that registered classes can be looked up in both directions."""
    empty_multi_registry.add_base(base_class=BaseClass)
    empty_multi_registry.register(class_=SubClassA, config_class=ConfigA, base_class=BaseClass)

    assert empty_multi_registry.get_class_by_config_class(config_class=ConfigA) is SubClassA
    assert empty_multi_registry.get_config_class_by_class(class_=SubClassA) is ConfigA


def test_registry_register_returns_the_registered_entry(
    empty_multi_registry: Registry,
    entry_for_sub_class_a: Entry,
) -> None:
    """Check that the returned entry is the one stored in the registry of its base class."""
    registry_base: RegistryBase[BaseClass] = empty_multi_registry.add_base(base_class=BaseClass)

    registered_entry: Entry[BaseClass] = empty_multi_registry.register(
        class_=SubClassA, config_class=ConfigA, base_class=BaseClass
    )

    assert registered_entry == entry_for_sub_class_a
    assert registry_base.get_entry_from_config_class(config_class=ConfigA) == registered_entry


def test_registry_register_raises_when_base_class_has_no_registry(
    empty_multi_registry: Registry,
) -> None:
    """Check that classes cannot be registered before their base class is added."""
    with pytest.raises(KeyError, match=r"No registry for"):
        empty_multi_registry.register(class_=SubClassA, config_class=ConfigA, base_class=BaseClass)


def test_registry_register_raises_when_class_is_not_subclass_of_base_class(
    empty_multi_registry: Registry,
) -> None:
    """Check that the entry validation is applied to the given classes."""
    empty_multi_registry.add_base(base_class=BaseClass)

    with pytest.raises(ValueError, match=r"is not a subclass of"):
        empty_multi_registry.register(class_=int, config_class=ConfigA, base_class=BaseClass)
