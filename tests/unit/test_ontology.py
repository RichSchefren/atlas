"""Unit tests for Atlas Phase 1 ontology — verifies all 8 types instantiate cleanly
and field-name collision check fires correctly."""

import pytest
from datetime import datetime, date, timezone
from decimal import Decimal

from atlas_core.ontology import (
    PHASE_1_ENTITY_TYPES,
    EDGE_TYPE_MAP,
    StructuralEdgeType,
    DomainEdgeType,
    Rich,
    Person,
    Program,
    Commitment,
    MarketEntity,
    Revenue,
    Project,
    StrategicBelief,
    HealthState,
    PsychReport,
    FinancialSnapshot,
    ClosenessSignals,
    FinancialRelationship,
    FinRelType,
    ImportanceTier,
    PriorityTier,
    ReciprocityState,
    EnrollmentStatus,
    LifecycleStage,
    CommitmentStatus,
    StakeLevel,
    MarketEntityType,
    ThreatLevel,
    PriceRange,
    Period,
    RevenueType,
    ProjectStatus,
    ProjectHealth,
    Milestone,
    ConfidenceLabel,
    CONFIDENCE_LABEL_DEFAULTS,
    CONFIDENCE_TRANSITION_HYSTERESIS,
)
from atlas_core.ontology.base import AtlasEntity, GRAPHITI_RESERVED_FIELDS


class TestPhase1EntityRegistry:
    """The PHASE_1_ENTITY_TYPES dict is what Atlas passes to add_episode(entity_types=...)."""

    def test_eight_entities_registered(self):
        assert len(PHASE_1_ENTITY_TYPES) == 8

    def test_all_entities_subclass_atlas_entity(self):
        for name, cls in PHASE_1_ENTITY_TYPES.items():
            assert issubclass(cls, AtlasEntity), f"{name} is not an AtlasEntity subclass"

    def test_no_field_name_collisions_with_graphiti_reserved(self):
        """The AtlasEntity __pydantic_init_subclass__ enforces this at class-def time;
        this test is belt-and-suspenders documentation."""
        for name, cls in PHASE_1_ENTITY_TYPES.items():
            for field_name in cls.model_fields:
                assert field_name not in GRAPHITI_RESERVED_FIELDS, (
                    f"{name}.{field_name} collides with Graphiti reserved field"
                )


class TestRich:
    def test_minimal_rich(self):
        rich = Rich()
        assert rich.psychological_profiles == []
        assert rich.current_priorities == []

    def test_rich_with_psych_report(self):
        report = PsychReport(
            report_type="Enneagram",
            date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            key_findings=["Type 7 with 8 wing", "High Drive"],
            full_document_path="vault/personal/enneagram-2024.md",
        )
        rich = Rich(psychological_profiles=[report])
        assert len(rich.psychological_profiles) == 1
        assert rich.psychological_profiles[0].report_type == "Enneagram"

    def test_rich_with_health_state(self):
        rich = Rich(
            current_health=HealthState(
                energy=8,
                sleep_last_night_hours=7.5,
                workout_completed_today=True,
                last_updated=datetime.now(timezone.utc),
            )
        )
        assert rich.current_health.energy == 8

    def test_health_state_validates_energy_bounds(self):
        with pytest.raises(Exception):
            HealthState(energy=11, last_updated=datetime.now(timezone.utc))
        with pytest.raises(Exception):
            HealthState(energy=0, last_updated=datetime.now(timezone.utc))


class TestPerson:
    def test_minimal_person(self):
        p = Person(person_role="Coach")
        assert p.person_role == "Coach"
        assert p.importance_tier == ImportanceTier.PERIPHERAL
        assert p.closeness_score == 0.0

    def test_person_with_financial_relationship(self):
        p = Person(
            person_role="JV Partner",
            importance_tier=ImportanceTier.STRATEGIC,
            financial_relationship=FinancialRelationship(
                type=FinRelType.JV_PARTNER,
                priority_level=PriorityTier.TIER_1,
                annual_value=Decimal("250000"),
                reciprocity_state=ReciprocityState.BALANCED,
            ),
        )
        assert p.financial_relationship.type == FinRelType.JV_PARTNER
        assert p.financial_relationship.annual_value == Decimal("250000")

    def test_closeness_signals_default_zero(self):
        signals = ClosenessSignals()
        assert signals.limitless_mentions_90d == 0
        assert signals.imessage_messages_90d == 0
        assert signals.last_interaction_date is None

    def test_closeness_score_bounded(self):
        with pytest.raises(Exception):
            Person(person_role="Test", closeness_score=1.5)
        with pytest.raises(Exception):
            Person(person_role="Test", closeness_score=-0.1)


class TestProgram:
    def test_minimal_program(self):
        p = Program(program_type="mastermind")
        assert p.program_type == "mastermind"
        assert p.enrollment_status == EnrollmentStatus.DORMANT
        assert p.lifecycle_stage == LifecycleStage.IDEATION

    def test_zenithpro_example(self):
        p = Program(
            program_type="mastermind",
            deliverables=["Weekly group coaching", "1:1 strategy", "AI implementation"],
            enrollment_status=EnrollmentStatus.ACTIVE,
            lifecycle_stage=LifecycleStage.MATURE,
            runner_kref="kref://Atlas/People/rich.person",
        )
        assert "Weekly group coaching" in p.deliverables


class TestCommitment:
    def test_minimal_commitment(self):
        c = Commitment(
            description="Send proposal by Friday",
            owner_kref="kref://Atlas/People/ashley.person",
        )
        assert c.status == CommitmentStatus.OPEN
        assert c.stakes == StakeLevel.MEDIUM

    def test_commitment_with_dependencies(self):
        c = Commitment(
            description="Launch ZenithPro Q3 cohort",
            owner_kref="kref://Atlas/Rich",
            counterparty_kref="kref://Atlas/Programs/zenithpro.program",
            deadline=datetime(2026, 9, 30, tzinfo=timezone.utc),
            depends_on_krefs=[
                "kref://Atlas/Projects/zp_curriculum_refresh.project",
                "kref://Atlas/Projects/zp_landing_page.project",
            ],
            stakes=StakeLevel.HIGH,
        )
        assert len(c.depends_on_krefs) == 2


class TestMarketEntity:
    def test_minimal_market_entity(self):
        m = MarketEntity(entity_market_type=MarketEntityType.COMPETITOR)
        assert m.threat_level == ThreatLevel.LOW
        assert m.strengths == []

    def test_market_entity_with_pricing(self):
        m = MarketEntity(
            entity_market_type=MarketEntityType.COMPETITOR,
            positioning="Premium coaching for SaaS founders",
            pricing_range=PriceRange(
                low_usd=Decimal("997"),
                high_usd=Decimal("4997"),
                typical_usd=Decimal("2497"),
            ),
            threat_level=ThreatLevel.MEDIUM,
        )
        assert m.pricing_range.typical_usd == Decimal("2497")


class TestRevenue:
    def test_minimal_revenue(self):
        r = Revenue(
            source="ZenithPro Q1 2026",
            amount_usd=Decimal("125000"),
            period=Period.QUARTERLY,
            period_start=date(2026, 1, 1),
            revenue_type=RevenueType.SUBSCRIPTION,
        )
        assert r.amount_usd == Decimal("125000")


class TestProject:
    def test_minimal_project(self):
        p = Project(owner_kref="kref://Atlas/Rich")
        assert p.project_status == ProjectStatus.PLANNING
        assert p.health == ProjectHealth.GREEN

    def test_project_with_milestones(self):
        p = Project(
            owner_kref="kref://Atlas/Rich",
            milestones=[
                Milestone(label="Spec lock", completed=True),
                Milestone(label="MVP demo", completed=False,
                          target_date=datetime(2026, 6, 1, tzinfo=timezone.utc)),
            ],
        )
        assert p.milestones[0].completed
        assert not p.milestones[1].completed


class TestStrategicBelief:
    def test_minimal_belief(self):
        b = StrategicBelief(
            hypothesis="ZenithPro is positioned in the premium tier of coaching market",
            confidence_label=ConfidenceLabel.WORKING_HYPOTHESIS,
            confidence_score=0.6,
        )
        assert b.confidence_label == ConfidenceLabel.WORKING_HYPOTHESIS
        assert not b.is_core_conviction

    def test_confidence_label_defaults_match(self):
        assert CONFIDENCE_LABEL_DEFAULTS[ConfidenceLabel.UNSTATED_ASSUMPTION] == 0.40
        assert CONFIDENCE_LABEL_DEFAULTS[ConfidenceLabel.WORKING_HYPOTHESIS] == 0.60
        assert CONFIDENCE_LABEL_DEFAULTS[ConfidenceLabel.VALIDATED_BELIEF] == 0.80
        assert CONFIDENCE_LABEL_DEFAULTS[ConfidenceLabel.CORE_CONVICTION] == 0.95

    def test_hysteresis_constant(self):
        assert CONFIDENCE_TRANSITION_HYSTERESIS == 0.05

    def test_core_conviction_flag(self):
        b = StrategicBelief(
            hypothesis="Open-source matches commercial SOTA when properly architected",
            confidence_label=ConfidenceLabel.CORE_CONVICTION,
            confidence_score=0.95,
            is_core_conviction=True,
        )
        assert b.is_core_conviction


class TestEdges:
    def test_six_structural_edges(self):
        expected = {
            "DEPENDS_ON",
            "DERIVED_FROM",
            "SUPERSEDES",
            "REFERENCED",
            "CONTAINS",
            "CREATED_FROM",
        }
        actual = {e.value for e in StructuralEdgeType}
        assert actual == expected

    def test_ten_domain_edges(self):
        expected = {
            "COMMITS_TO",
            "OWNS",
            "RUNS",
            "GENERATES",
            "CONTRADICTS",
            "SUPPORTS",
            "COMPETES_WITH",
            "IMPORTANT_TO_RICH",
            "ORBITS",
            "FINANCIAL_RELATIONSHIP",
        }
        actual = {e.value for e in DomainEdgeType}
        assert actual == expected

    def test_edge_type_map_has_default_catchall(self):
        assert ("Entity", "Entity") in EDGE_TYPE_MAP

    def test_edge_type_map_includes_orbits_to_rich(self):
        assert DomainEdgeType.ORBITS.value in EDGE_TYPE_MAP[("Person", "Rich")]
        assert DomainEdgeType.ORBITS.value in EDGE_TYPE_MAP[("Program", "Rich")]
        assert DomainEdgeType.ORBITS.value in EDGE_TYPE_MAP[("Project", "Rich")]


class TestFieldCollisionGuard:
    def test_collision_guard_raises_on_reserved_name(self):
        """The AtlasEntity base validates field names at class definition time."""
        with pytest.raises(ValueError, match="reserved Graphiti EntityNode field"):
            class BadEntity(AtlasEntity):
                uuid: str  # collides with Graphiti's reserved 'uuid'
