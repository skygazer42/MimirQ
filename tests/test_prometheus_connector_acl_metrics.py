from app.core.config import settings
from app.core.metrics import render_metrics
from app.services.connector_acl_prometheus_metrics import (
    observe_connector_acl_apply,
    observe_connector_acl_apply_error,
)


def test_prometheus_connector_acl_metrics_export(monkeypatch):
    monkeypatch.setattr(settings, "PROMETHEUS_ENABLED", True, raising=False)

    observe_connector_acl_apply(connector_id="github_repo", mode="partial_members", member_count=0, group_count=2)
    observe_connector_acl_apply_error(connector_id="github_repo", mode="partial_members")

    body, _content_type = render_metrics()
    text = body.decode("utf-8", "ignore")

    assert "# TYPE connector_acl_apply_total counter" in text
    assert "# TYPE connector_acl_apply_errors_total counter" in text
    assert 'connector_acl_apply_total{connector_id="github_repo",mode="partial_members",shape="groups_only"}' in text
    assert 'connector_acl_apply_errors_total{connector_id="github_repo",mode="partial_members"}' in text

