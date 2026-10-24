"""Unit tests for client_config.py verifying candidate profiles, roles, and exclusion lists."""

from pathlib import Path

from client_config import (
    BENCH_MARKETING_PHRASES,
    CANDIDATE_ROLES,
    CLIENTS,
    NON_USA_INDICATORS,
    USA_GEO_INDICATORS,
    get_candidate_by_id,
    get_role_definition,
)


def test_candidate_roles_completeness():
    assert "java_developer" in CANDIDATE_ROLES
    assert "python_developer" in CANDIDATE_ROLES
    assert ".net_developer" in CANDIDATE_ROLES or "dotnet_developer" in CANDIDATE_ROLES

    java_role = get_role_definition("java_developer")
    assert java_role is not None
    assert len(java_role.search_roles) >= 1
    assert "devops" in java_role.exclusion_keywords
    assert "qa" in java_role.exclusion_keywords


def test_clients_and_dummy_candidate():
    assert len(CLIENTS) >= 1
    dummy = get_candidate_by_id("alex_johnson_dummy")
    assert dummy is not None
    assert dummy.name == "Alex Johnson"
    assert dummy.primary_role == "Java Full Stack Developer"
    assert len(dummy.skills) >= 5

    resume_path = dummy.get_absolute_resume_path(Path("/fake/base"))
    assert resume_path.name == "dummy_alex_johnson.docx"


def test_bench_marketing_and_geo_phrases():
    assert len(BENCH_MARKETING_PHRASES) >= 5
    assert "on my bench" in BENCH_MARKETING_PHRASES
    assert "hotlist" in BENCH_MARKETING_PHRASES

    assert len(NON_USA_INDICATORS) >= 10
    assert "pune" in NON_USA_INDICATORS
    assert "india" in NON_USA_INDICATORS

    assert len(USA_GEO_INDICATORS) >= 20
    assert "usa" in USA_GEO_INDICATORS
    assert "tx" in USA_GEO_INDICATORS
