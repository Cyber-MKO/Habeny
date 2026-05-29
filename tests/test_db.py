"""
Tests for the database layer (db.py).

These can run immediately — they only need sqlite3 and the db module.
"""
from db import (
    get_or_create_agent_seq_id,
    get_agent_by_name,
    upsert_agent,
    mark_agent_deleted,
    create_group,
    list_groups,
    group_exists,
    get_agents_in_group,
    assign_agents_to_group,
    remove_agents_from_group,
    rename_group,
    delete_group,
)


def test_get_or_create_seq_id_returns_incrementing_ids(tmp_db):
    id1 = get_or_create_agent_seq_id(tmp_db, "agent-a")
    id2 = get_or_create_agent_seq_id(tmp_db, "agent-b")
    assert id2 == id1 + 1


def test_get_or_create_seq_id_is_idempotent(tmp_db):
    id1 = get_or_create_agent_seq_id(tmp_db, "agent-a")
    id2 = get_or_create_agent_seq_id(tmp_db, "agent-a")
    assert id1 == id2


def test_upsert_and_get_agent(tmp_db):
    seq_id = get_or_create_agent_seq_id(tmp_db, "agent-x")
    upsert_agent(tmp_db, "agent-x", {
        "seq_id": seq_id,
        "siem_type": "wazuh",
        "ip_addresses": ["10.0.0.1"],
    })
    agent = get_agent_by_name(tmp_db, "agent-x")
    assert agent is not None
    assert agent["siem_type"] == "wazuh"
    assert agent["ip_addresses"] == ["10.0.0.1"]


def test_get_agent_returns_none_for_unknown(tmp_db):
    assert get_agent_by_name(tmp_db, "no-such-agent") is None


def test_mark_agent_deleted(tmp_db):
    get_or_create_agent_seq_id(tmp_db, "agent-d")
    mark_agent_deleted(tmp_db, "agent-d")
    agent = get_agent_by_name(tmp_db, "agent-d")
    assert agent["deleted_at"] is not None


def test_group_lifecycle(tmp_db):
    assert not group_exists(tmp_db, "grp1")
    create_group(tmp_db, "grp1", "test group")
    assert group_exists(tmp_db, "grp1")

    groups = list_groups(tmp_db)
    assert len(groups["groups"]) == 1
    assert groups["groups"][0]["name"] == "grp1"


def test_assign_and_remove_agents_from_group(tmp_db):
    create_group(tmp_db, "grp1")
    get_or_create_agent_seq_id(tmp_db, "a1")
    get_or_create_agent_seq_id(tmp_db, "a2")

    assign_agents_to_group(tmp_db, "grp1", ["a1", "a2"])
    assert sorted(get_agents_in_group(tmp_db, "grp1")) == ["a1", "a2"]

    remove_agents_from_group(tmp_db, ["a1"])
    assert get_agents_in_group(tmp_db, "grp1") == ["a2"]


def test_rename_group(tmp_db):
    create_group(tmp_db, "old")
    get_or_create_agent_seq_id(tmp_db, "a1")
    assign_agents_to_group(tmp_db, "old", ["a1"])

    result = rename_group(tmp_db, "old", "new")
    assert result["name"] == "new"
    assert not group_exists(tmp_db, "old")
    assert group_exists(tmp_db, "new")
    assert get_agents_in_group(tmp_db, "new") == ["a1"]


def test_delete_group_unassigns_agents(tmp_db):
    create_group(tmp_db, "grp")
    get_or_create_agent_seq_id(tmp_db, "a1")
    assign_agents_to_group(tmp_db, "grp", ["a1"])

    removed = delete_group(tmp_db, "grp")
    assert removed == 1
    assert not group_exists(tmp_db, "grp")
    agent = get_agent_by_name(tmp_db, "a1")
    assert agent["agent_group"] is None
