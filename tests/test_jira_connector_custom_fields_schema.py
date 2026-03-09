from __future__ import annotations


def test_jira_project_connector_config_supports_custom_fields_allowlist():  # noqa: ANN001
    from app.api.schemas.connector import JiraProjectConnectorConfig

    assert "custom_fields" in JiraProjectConnectorConfig.model_fields
    assert "include_linked_artifacts" in JiraProjectConnectorConfig.model_fields
    assert "max_linked_artifacts_per_issue" in JiraProjectConnectorConfig.model_fields
    assert "max_total_linked_artifacts" in JiraProjectConnectorConfig.model_fields

    cfg = JiraProjectConnectorConfig(
        base_url="https://example.atlassian.net",
        project_key="plat",
        custom_fields=[
            " customfield_10016 ",
            "CUSTOMFIELD_10016",
            "customfield_10017",
            "not_a_field",
            "",
        ],
        include_linked_artifacts=True,
        max_linked_artifacts_per_issue=10,
        max_total_linked_artifacts=20,
    )

    assert cfg.custom_fields == [
        "customfield_10016",
        "customfield_10017",
    ]
