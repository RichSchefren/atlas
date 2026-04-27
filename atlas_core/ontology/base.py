"""Shared base for Atlas Pydantic entity types.

Atlas entity types are stored as Graphiti EntityNode `attributes` dict + Neo4j label.
Field name collision check: Atlas types must not use Graphiti EntityNode reserved
field names (uuid, name, group_id, labels, created_at, name_embedding, summary,
attributes). All Phase 1 types verified to comply.
"""

from pydantic import BaseModel, ConfigDict

GRAPHITI_RESERVED_FIELDS = frozenset({
    "uuid",
    "name",
    "group_id",
    "labels",
    "created_at",
    "name_embedding",
    "summary",
    "attributes",
})


class AtlasEntity(BaseModel):
    """Base for all Atlas typed entities. Pydantic v2.

    Subclass docstring becomes the LLM-facing entity description (Graphiti
    convention). Field descriptions become the LLM-facing attribute hints.
    Field names cannot collide with Graphiti EntityNode reserved fields.
    """

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=False,
        validate_assignment=True,
    )

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs):
        """Validate subclass field names at class-definition time.

        Raises ValueError if any field collides with Graphiti EntityNode reserved
        fields. Catches ontology bugs early instead of at first ingest.
        """
        super().__pydantic_init_subclass__(**kwargs)
        for field_name in cls.model_fields:
            if field_name in GRAPHITI_RESERVED_FIELDS:
                raise ValueError(
                    f"AtlasEntity subclass {cls.__name__} uses reserved Graphiti "
                    f"EntityNode field name {field_name!r}. Reserved: "
                    f"{sorted(GRAPHITI_RESERVED_FIELDS)}"
                )
