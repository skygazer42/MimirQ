from __future__ import annotations

import contextlib
import html
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.models.document import Document as DBDocument

JIRA_UPDATED_SOURCE = "connector:jira:updated"


def _resolve_connectors_attr(name: str):  # noqa: ANN202
    leader_module = globals().get("_leader_module")
    if leader_module is not None and hasattr(leader_module, name):
        return getattr(leader_module, name)

    preferred_modules = (
        "test_support_connectors_module",
        "app.api.v1.connectors",
    )
    for module_name in preferred_modules:
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, name):
            return getattr(module, name)

    for module in reversed(tuple(sys.modules.values())):
        path = str(getattr(module, "__file__", "") or "")
        if not path.endswith("/app/api/v1/connectors.py"):
            continue
        if hasattr(module, name):
            return getattr(module, name)

    raise RuntimeError(f"connectors attr not available: {name}")


def _resolve_connectors_helper(name: str):  # noqa: ANN202
    helper = _resolve_connectors_attr(name)
    if callable(helper):
        return helper
    raise RuntimeError(f"connectors helper not available: {name}")


def _jira_api_base_url(base_url: str) -> str:
    """
    Normalize a Jira base URL to the Jira Cloud REST v3 API base.

    Examples:
    - https://<site>.atlassian.net -> https://<site>.atlassian.net/rest/api/3
    - https://<site>.atlassian.net/rest/api/3 -> unchanged
    """
    base = str(base_url or "").strip().rstrip("/")
    if base.endswith("/rest/api/3"):
        return base
    if base.endswith("/rest/api"):
        return f"{base}/3"
    if "/rest/api/" in base:
        prefix = base.split("/rest/api/", 1)[0].rstrip("/")
        return f"{prefix}/rest/api/3"
    return f"{base}/rest/api/3"


async def _jira_request(pool, method: str, url: str, **kwargs):  # noqa: ANN001, ANN201
    """
    Jira API requests are always third-party outbound HTTP calls.
    """
    return await pool.request_with_retry(method, url, use_external_client=True, **kwargs)


def _jira_extract_issue_updated(issue: dict) -> str | None:
    """
    Best-effort extraction of the Jira issue updated timestamp for incremental cursoring.
    """
    if not isinstance(issue, dict):
        return None
    fields = issue.get("fields")
    if isinstance(fields, dict):
        updated = str(fields.get("updated") or "").strip()
        if updated:
            return updated
    updated = str(issue.get("updated") or "").strip()
    return updated or None


def _jira_principal_value(raw: object) -> str:
    value = str(raw or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    return value[:255]


def _jira_group_principal_key(group_name: str) -> str:
    name = _jira_principal_value(group_name)
    return f"jira:group:{name}"[:255] if name else ""


def _jira_role_principal_key(role_name: str) -> str:
    name = _jira_principal_value(role_name)
    return f"jira:role:{name}"[:255] if name else ""


def _jira_security_level_principal_key(security: object) -> str:
    if not isinstance(security, dict):
        return ""
    level_id = str(security.get("id") or "").strip()
    if level_id:
        return f"jira:policy:security-level/{level_id}"[:255]
    name = _jira_principal_value(security.get("name"))
    if not name:
        return ""
    return f"jira:policy:security-level/{name}"[:255]


def _jira_issue_acl_principal_keys(issue: dict, *, include_comments: bool, max_comments: int) -> tuple[bool, list[str]]:
    """
    Collect best-effort Jira visibility/security handles for source ACL inheritance.

    We do not attempt to resolve Jira memberships here. Instead we expose stable external ids
    that operators can map onto tenant groups via `tenant_groups.external_id`.
    """
    if not isinstance(issue, dict):
        return False, []

    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return False, []

    keys: set[str] = set()

    security_key = _jira_security_level_principal_key(fields.get("security"))
    if security_key:
        keys.add(security_key)

    if include_comments:
        lim = max(0, int(max_comments or 0))
        comments_obj = fields.get("comment")
        comments = comments_obj.get("comments") if isinstance(comments_obj, dict) else None
        items = comments if isinstance(comments, list) else []
        for comment in items[:lim]:
            if not isinstance(comment, dict):
                continue
            visibility = comment.get("visibility")
            if not isinstance(visibility, dict):
                continue
            vis_type = str(visibility.get("type") or "").strip().lower()
            vis_value = visibility.get("value") or visibility.get("identifier") or visibility.get("name")
            if vis_type == "group":
                key = _jira_group_principal_key(str(vis_value or ""))
            elif vis_type == "role":
                key = _jira_role_principal_key(str(vis_value or ""))
            else:
                key = ""
            if key:
                keys.add(key)

    ordered = sorted(keys)
    return bool(ordered), ordered


def _jira_adf_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_jira_adf_to_text(item) for item in value)
    if not isinstance(value, dict):
        return str(value)

    node_type = str(value.get("type") or "").strip().lower()
    if node_type == "text":
        return str(value.get("text") or "")
    if node_type == "hardbreak":
        return "\n"

    content = value.get("content")
    child_items = content if isinstance(content, list) else []
    text = "".join(_jira_adf_to_text(item) for item in child_items)
    if node_type in {"paragraph", "heading", "listitem", "blockquote", "tablecell", "tableheader"} and text and not text.endswith("\n"):
        text += "\n"
    return text


def _jira_adf_is_doc(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return str(value.get("type") or "").strip().lower() == "doc" and isinstance(value.get("content"), list)


def _jira_adf_text_node_html(value: dict) -> str:
    text = html.escape(str(value.get("text") or ""))

    marks = value.get("marks") if isinstance(value.get("marks"), list) else []
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        mtype = str(mark.get("type") or "").strip().lower()
        if mtype == "link":
            attrs = mark.get("attrs") if isinstance(mark.get("attrs"), dict) else {}
            href = str(attrs.get("href") or "").strip()
            if _resolve_connectors_helper("_is_link_href_allowed")(href):
                text = f'<a href="{html.escape(href)}">{text}</a>'
            continue
        if mtype == "strong":
            text = f"<strong>{text}</strong>"
            continue
        if mtype == "em":
            text = f"<em>{text}</em>"
            continue
        if mtype == "code":
            text = f"<code>{text}</code>"
            continue
        if mtype in {"strike", "strikethrough"}:
            text = f"<s>{text}</s>"

    return text


def _jira_adf_render_child_nodes(child_items: list[object], *, depth: int, separator: str) -> str:
    return separator.join(_jira_adf_node_to_html(item, depth=depth + 1) for item in child_items).strip()


def _jira_adf_node_html_paragraph(value: dict, child_items: list[object], depth: int) -> str:
    inner = _jira_adf_render_child_nodes(child_items, depth=depth, separator="")
    if not inner:
        return ""
    return f"<p>{inner}</p>"


def _jira_adf_node_html_heading(value: dict, child_items: list[object], depth: int) -> str:
    attrs = value.get("attrs") if isinstance(value.get("attrs"), dict) else {}
    try:
        level = int(attrs.get("level") or 3)
    except Exception:
        level = 3
    level = max(1, min(level, 6))

    inner = _jira_adf_render_child_nodes(child_items, depth=depth, separator="")
    if not inner:
        return ""

    safe_level = min(6, max(3, level + 1))
    return f"<h{safe_level}>{inner}</h{safe_level}>"


def _jira_adf_node_html_blockquote(value: dict, child_items: list[object], depth: int) -> str:
    inner = _jira_adf_render_child_nodes(child_items, depth=depth, separator="\n")
    if not inner:
        return ""
    return f"<blockquote>{inner}</blockquote>"


def _jira_adf_node_html_hr(value: dict, child_items: list[object], depth: int) -> str:
    return "<hr />"


def _jira_adf_node_html_bullet_list(value: dict, child_items: list[object], depth: int) -> str:
    inner = _jira_adf_render_child_nodes(child_items, depth=depth, separator="\n")
    if not inner:
        return ""
    return f"<ul>{inner}</ul>"


def _jira_adf_node_html_ordered_list(value: dict, child_items: list[object], depth: int) -> str:
    inner = _jira_adf_render_child_nodes(child_items, depth=depth, separator="\n")
    if not inner:
        return ""
    return f"<ol>{inner}</ol>"


def _jira_adf_node_html_list_item(value: dict, child_items: list[object], depth: int) -> str:
    inner = _jira_adf_render_child_nodes(child_items, depth=depth, separator="\n")
    if not inner:
        return ""
    return f"<li>{inner}</li>"


def _jira_adf_node_html_code_block(value: dict, child_items: list[object], depth: int) -> str:
    code_text = _jira_adf_to_text(value).strip("\n")
    if not code_text.strip():
        return ""
    return f"<pre><code>{html.escape(code_text)}</code></pre>"


def _jira_adf_node_html_table(value: dict, child_items: list[object], depth: int) -> str:
    inner = _jira_adf_render_child_nodes(child_items, depth=depth, separator="\n")
    if not inner:
        return ""
    return f"<table><tbody>{inner}</tbody></table>"


def _jira_adf_node_html_table_row(value: dict, child_items: list[object], depth: int) -> str:
    inner = _jira_adf_render_child_nodes(child_items, depth=depth, separator="")
    if not inner:
        return ""
    return f"<tr>{inner}</tr>"


def _jira_adf_node_html_table_cell(value: dict, child_items: list[object], depth: int) -> str:
    inner = _jira_adf_render_child_nodes(child_items, depth=depth, separator="\n")
    if not inner:
        return ""
    return f"<td>{inner}</td>"


def _jira_adf_node_html_table_header(value: dict, child_items: list[object], depth: int) -> str:
    inner = _jira_adf_render_child_nodes(child_items, depth=depth, separator="\n")
    if not inner:
        return ""
    return f"<th>{inner}</th>"


def _jira_adf_node_html_inline_card(value: dict, child_items: list[object], depth: int) -> str:
    attrs = value.get("attrs") if isinstance(value.get("attrs"), dict) else {}
    url = str(attrs.get("url") or "").strip()
    if _resolve_connectors_helper("_is_http_or_https_url")(url):
        esc = html.escape(url)
        return f'<a href="{esc}">{esc}</a>'
    return html.escape(url) if url else ""


def _jira_adf_node_html_mention(value: dict, child_items: list[object], depth: int) -> str:
    attrs = value.get("attrs") if isinstance(value.get("attrs"), dict) else {}
    text = str(attrs.get("text") or attrs.get("displayName") or "").strip()
    if text:
        return html.escape(text)
    return ""


def _jira_adf_node_html_emoji(value: dict, child_items: list[object], depth: int) -> str:
    attrs = value.get("attrs") if isinstance(value.get("attrs"), dict) else {}
    text = str(attrs.get("text") or attrs.get("shortName") or "").strip()
    if text:
        return html.escape(text)
    return ""


_JIRA_ADF_NODE_HTML_HANDLERS = {
    "blockquote": _jira_adf_node_html_blockquote,
    "bulletlist": _jira_adf_node_html_bullet_list,
    "codeblock": _jira_adf_node_html_code_block,
    "emoji": _jira_adf_node_html_emoji,
    "heading": _jira_adf_node_html_heading,
    "inlinecard": _jira_adf_node_html_inline_card,
    "listitem": _jira_adf_node_html_list_item,
    "mention": _jira_adf_node_html_mention,
    "orderedlist": _jira_adf_node_html_ordered_list,
    "paragraph": _jira_adf_node_html_paragraph,
    "rule": _jira_adf_node_html_hr,
    "table": _jira_adf_node_html_table,
    "tablecell": _jira_adf_node_html_table_cell,
    "tableheader": _jira_adf_node_html_table_header,
    "tablerow": _jira_adf_node_html_table_row,
}


def _jira_adf_node_to_html(value: object, *, depth: int = 0) -> str:
    if depth > 50:
        return ""
    if value is None:
        return ""
    if isinstance(value, str):
        return html.escape(value)
    if isinstance(value, list):
        return "\n".join(
            part for part in (_jira_adf_node_to_html(item, depth=depth + 1) for item in value) if part
        )
    if not isinstance(value, dict):
        return html.escape(str(value))

    node_type = str(value.get("type") or "").strip().lower()
    content = value.get("content")
    child_items = content if isinstance(content, list) else []

    if node_type == "text":
        return _jira_adf_text_node_html(value)
    if node_type == "hardbreak":
        return "<br />"

    handler = _JIRA_ADF_NODE_HTML_HANDLERS.get(node_type)
    if handler:
        return handler(value, child_items, depth)

    return _jira_adf_render_child_nodes(child_items, depth=depth, separator="\n")


def _jira_adf_to_html(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return "\n".join(f"<p>{html.escape(line.strip())}</p>" for line in value.splitlines() if line.strip())
    if isinstance(value, dict) and not _jira_adf_is_doc(value):
        return _jira_adf_node_to_html(value)
    return _jira_adf_node_to_html(value)


def _jira_mapping_text(value: dict[str, Any]) -> str:
    for key in ("displayName", "name", "value", "key", "title", "summary"):
        raw = value.get(key)
        if raw is None:
            continue
        if isinstance(raw, (str, int, float, bool)):
            text = str(raw).strip()
            if text:
                return text
    return ""


def _jira_value_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if _jira_adf_is_doc(value):
        return _jira_adf_to_text(value)
    if isinstance(value, list):
        parts = [(_jira_value_to_text(item) or "").strip() for item in value]
        parts = [p for p in parts if p]
        return ", ".join(parts)
    if isinstance(value, dict):
        return _jira_mapping_text(value)
    return str(value).strip()


def _jira_html_from_value(raw: object) -> str:
    if raw is None:
        return ""
    if _jira_adf_is_doc(raw):
        return _jira_adf_to_html(raw)
    text = _jira_value_to_text(raw).strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(f"<p>{html.escape(line)}</p>" for line in lines)


def _jira_html_from_field(*, rendered: object, raw: object) -> str:
    rendered_text = str(rendered or "").strip() if isinstance(rendered, str) else ""
    if rendered_text:
        return rendered_text

    if _jira_adf_is_doc(raw):
        return _jira_adf_to_html(raw)

    return _jira_html_from_value(raw)


def _jira_issue_url(*, base_url: str, issue_key: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    key = str(issue_key or "").strip()
    if not base or not key:
        return ""
    return f"{base}/browse/{quote(key, safe='')}"


def _soft_disable_jira_documents_missing_from_full_sync(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    base_url: str,
    project_key: str,
    seen_issue_urls: set[str],
    connector_id: str = "jira_project",
    max_docs_scan: int = 5000,
) -> tuple[int, int]:
    """
    Best-effort soft-disable for Jira issue documents missing from a complete full sync.

    Scope is limited to connector-managed Jira docs for the same tenant/dataset/base URL/project.
    """
    if dataset_id is None:
        return 0, 0

    base_url = str(base_url or "").strip().rstrip("/")
    project_key = str(project_key or "").strip().upper()
    connector_id = str(connector_id or "jira_project").strip() or "jira_project"
    seen_urls = {
        str(url or "").strip()
        for url in (seen_issue_urls or set())
        if str(url or "").strip()
    }
    if not base_url or not project_key:
        return 0, 0

    docs: list[Any]
    try:
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == connector_id)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == base_url)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["project_key"].astext == project_key)  # type: ignore[attr-defined]
            .order_by(DBDocument.created_at.desc())
            .all()
        )
    except Exception:
        max_docs_scan = max(0, int(max_docs_scan or 0))
        if max_docs_scan <= 0:
            max_docs_scan = 5000
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .order_by(DBDocument.created_at.desc())
            .limit(max_docs_scan)
            .all()
        )

    now = _resolve_connectors_helper("_now")()
    disabled = 0
    reconciled_issue_urls: set[str] = set()
    for doc in docs or []:
        if getattr(doc, "archived_at", None) is not None:
            continue
        meta = doc.doc_metadata if isinstance(getattr(doc, "doc_metadata", None), dict) else {}
        conn = meta.get("connector") if isinstance(meta.get("connector"), dict) else {}
        if str(conn.get("connector_id") or "") != connector_id:
            continue
        if str(conn.get("base_url") or "").strip().rstrip("/") != base_url:
            continue
        if str(conn.get("project_key") or "").strip().upper() != project_key:
            continue

        issue_url = str(conn.get("issue_url") or meta.get("source_url") or "").strip()
        if not issue_url or issue_url in seen_urls:
            continue

        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            reconciled_issue_urls.add(issue_url)
            disabled += 1

    return len(reconciled_issue_urls), int(disabled)


def _jira_jql_updated_after(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    normalized = _resolve_connectors_helper("_normalize_datetime_utc_iso")(text)
    if not normalized:
        return text
    dt = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m-%d %H:%M")


def _jira_issue_fields(issue: dict) -> dict:
    fields = issue.get("fields")
    return fields if isinstance(fields, dict) else {}


def _jira_issue_rendered_fields(issue: dict) -> dict:
    rendered = issue.get("renderedFields")
    return rendered if isinstance(rendered, dict) else {}


def _jira_issue_field_name(fields: dict, key: str) -> str:
    raw = fields.get(key)
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("name") or "").strip()


def _jira_issue_label_text(fields: dict) -> str:
    labels = fields.get("labels")
    if not isinstance(labels, list):
        return ""
    cleaned = [str(label or "").strip() for label in labels if str(label or "").strip()]
    return ", ".join(cleaned)


def _jira_comment_items(fields: dict) -> list[dict]:
    comments_obj = fields.get("comment")
    if not isinstance(comments_obj, dict):
        return []
    comments = comments_obj.get("comments")
    if not isinstance(comments, list):
        return []
    return [comment for comment in comments if isinstance(comment, dict)]


def _jira_rendered_comment_items(rendered: dict) -> list[dict]:
    rendered_comments_obj = rendered.get("comment")
    if not isinstance(rendered_comments_obj, dict):
        return []
    comments = rendered_comments_obj.get("comments")
    if not isinstance(comments, list):
        return []
    return [comment for comment in comments if isinstance(comment, dict)]


def _jira_rendered_comment_at(rendered_comment_items: list[dict], idx: int) -> dict:
    if idx <= 0:
        return {}
    offset = idx - 1
    if offset >= len(rendered_comment_items):
        return {}
    return rendered_comment_items[offset]


def _jira_comment_meta_html(comment: dict) -> str:
    author_obj = comment.get("author")
    author = str((author_obj or {}).get("displayName") or "").strip() if isinstance(author_obj, dict) else ""
    created = str(comment.get("created") or "").strip()
    meta_bits = [bit for bit in (author, created) if bit]
    if not meta_bits:
        return ""
    return f"<p><strong>Meta:</strong> {html.escape(' | '.join(meta_bits))}</p>"


def _jira_render_issue_comment_article(*, idx: int, comment: dict, rendered_comment: dict) -> str:
    body_html = _jira_html_from_field(
        rendered=rendered_comment.get("body"),
        raw=comment.get("body"),
    )
    meta_html = _jira_comment_meta_html(comment)
    return f"<article><h3>Comment {idx}</h3>{meta_html}{body_html}</article>"


def _jira_render_issue_comment_articles(*, fields: dict, rendered: dict, max_comments: int) -> list[str]:
    comment_items = _jira_comment_items(fields)
    rendered_comment_items = _jira_rendered_comment_items(rendered)

    out: list[str] = []
    lim = max(0, int(max_comments or 0))
    for idx, comment in enumerate(comment_items[:lim], start=1):
        rendered_comment = _jira_rendered_comment_at(rendered_comment_items, idx)
        out.append(_jira_render_issue_comment_article(idx=idx, comment=comment, rendered_comment=rendered_comment))

    return out


def _jira_render_custom_field_sections(*, fields: dict, rendered: dict) -> list[str]:
    custom_fields = [
        (key, raw_value)
        for k, raw_value in (fields or {}).items()
        if (key := str(k or "").strip()).startswith("customfield_")
    ]
    custom_fields.sort(key=lambda item: item[0])

    out: list[str] = []
    for key, raw_value in custom_fields:
        value_html = _jira_html_from_field(
            rendered=rendered.get(key),
            raw=raw_value,
        )
        if not value_html:
            continue
        out.append(
            "<article>"
            f"<h3>{html.escape(key)}</h3>"
            f"{value_html}"
            "</article>"
        )
    return out


def _jira_render_issue_document_preamble(*, issue_key: str, summary: str, issue_url: str, base_url: str) -> list[str]:
    base_href = issue_url or str(base_url or "")
    base_tag = f'  <base href="{html.escape(base_href)}" />' if base_href else ""
    return [
        "<!doctype html>",
        "<html>",
        "<head>",
        '  <meta charset="utf-8" />',
        f"  <title>{html.escape(issue_key or summary)}</title>",
        base_tag,
        "</head>",
        "<body>",
        f"  <h1>{html.escape(issue_key or 'Jira Issue')}</h1>",
        "  <h2>Summary</h2>",
        f"  <p>{html.escape(summary)}</p>",
    ]


def _jira_render_issue_meta_paragraphs(
    *,
    issue_url: str,
    issue_type: str,
    priority: str,
    status: str,
    updated: str,
    label_text: str,
) -> list[str]:
    out: list[str] = []
    if issue_url:
        esc = html.escape(issue_url)
        out.append(f'  <p><strong>Issue URL:</strong> <a href="{esc}">{esc}</a></p>')

    for label, value in (
        ("Issue Type", issue_type),
        ("Priority", priority),
        ("Status", status),
        ("Updated", updated),
        ("Labels", label_text),
    ):
        if not value:
            continue
        out.append(f"  <p><strong>{label}:</strong> {html.escape(value)}</p>")

    return out


def _jira_render_issue_html(*, base_url: str, issue: dict, include_comments: bool, max_comments: int) -> str:
    """
    Render a Jira issue into a stable HTML document shape that works with `jira_ticket`.
    """
    issue = issue if isinstance(issue, dict) else {}
    fields = _jira_issue_fields(issue)
    rendered = _jira_issue_rendered_fields(issue)

    issue_key = str(issue.get("key") or "").strip()
    summary = str(fields.get("summary") or issue_key or "Jira issue").strip()
    issue_url = _jira_issue_url(base_url=base_url, issue_key=issue_key)
    updated = _jira_extract_issue_updated(issue) or ""

    issue_type = _jira_issue_field_name(fields, "issuetype")
    priority = _jira_issue_field_name(fields, "priority")
    status = _jira_issue_field_name(fields, "status")
    label_text = _jira_issue_label_text(fields)

    description_html = _jira_html_from_field(
        rendered=rendered.get("description"),
        raw=fields.get("description"),
    )

    comments_html = (
        _jira_render_issue_comment_articles(fields=fields, rendered=rendered, max_comments=max_comments)
        if include_comments
        else []
    )
    parts = _jira_render_issue_document_preamble(
        issue_key=issue_key,
        summary=summary,
        issue_url=issue_url,
        base_url=base_url,
    )
    parts.extend(
        _jira_render_issue_meta_paragraphs(
            issue_url=issue_url,
            issue_type=issue_type,
            priority=priority,
            status=status,
            updated=updated,
            label_text=label_text,
        )
    )
    custom_field_sections = _jira_render_custom_field_sections(fields=fields, rendered=rendered)
    if custom_field_sections:
        parts.extend(["  <h2>Custom Fields</h2>", *custom_field_sections])

    if description_html:
        parts.extend(["  <h2>Description</h2>", description_html])

    if comments_html:
        parts.extend(["  <h2>Comments</h2>", *comments_html])

    parts.extend(["</body>", "</html>"])
    return "\n".join(part for part in parts if part)


def _build_jira_project_run_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    base_url = str(cfg.get("base_url") or "").strip().rstrip("/")
    project_key = str(cfg.get("project_key") or "").strip().upper()
    if not base_url or not project_key:
        raise ValueError("base_url and project_key are required")

    sync_mode = str(cfg.get("sync_mode") or "auto").strip().lower()
    if sync_mode not in {"auto", "full", "incremental"}:
        sync_mode = "auto"

    state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}
    cursor_last_modified = str(state.get("last_modified") or "").strip() if isinstance(state, dict) else ""
    cursor_last_modified_ids = (
        set(_resolve_connectors_helper("normalize_boundary_ids")(state.get("last_modified_ids"))) if isinstance(state, dict) else set()
    )

    effective_mode = sync_mode
    if effective_mode == "auto":
        effective_mode = "incremental" if cursor_last_modified else "full"
    if effective_mode == "incremental" and not cursor_last_modified:
        effective_mode = "full"

    custom_fields_raw = cfg.get("custom_fields")
    custom_fields_in = custom_fields_raw if isinstance(custom_fields_raw, list) else []
    custom_fields: list[str] = []
    custom_fields_seen: set[str] = set()
    for raw in custom_fields_in:
        key = str(raw or "").strip().lower()
        if not key or len(key) > 80 or not re.fullmatch(r"customfield_\d+", key) or key in custom_fields_seen:
            continue
        custom_fields_seen.add(key)
        custom_fields.append(key)
        if len(custom_fields) >= 30:
            break

    include_attachments, max_attachments_per_issue, max_total_attachments = _resolve_connectors_helper("_jira_attachment_limits")(cfg)
    include_linked_artifacts, max_linked_artifacts_per_issue, max_total_linked_artifacts = _resolve_connectors_helper("_jira_linked_artifact_limits")(cfg)
    access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None
    source_acl = cfg.get("source_acl") if isinstance(cfg.get("source_acl"), dict) else None
    access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
    has_manual_access_override = bool(isinstance(access, dict) and access_mode != "inherit")
    source_acl_mode = (
        str(source_acl.get("mode") or "disabled").strip().lower() if isinstance(source_acl, dict) else "disabled"
    )
    source_acl_fallback_mode = (
        str(source_acl.get("fallback_mode") or "partial_members").strip().lower()
        if isinstance(source_acl, dict)
        else "partial_members"
    )
    user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None
    auth_headers = _resolve_connectors_helper("_build_auth_headers")(cfg)
    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": (user_agent or "MimirQ/1.0 (+jira_project)"),
    }
    headers.update(auth_headers)

    return {
        "base_url": base_url,
        "project_key": project_key,
        "effective_mode": effective_mode,
        "cursor_last_modified": cursor_last_modified,
        "cursor_last_modified_ids": cursor_last_modified_ids,
        "max_issues": max(1, min(int(cfg.get("max_issues") or 50), 500)),
        "page_size": max(1, min(int(cfg.get("page_size") or 25), 100)),
        "include_comments": bool(cfg.get("include_comments", True)),
        "max_comments_per_issue": max(0, min(int(cfg.get("max_comments_per_issue") or 20), 200)),
        "custom_fields": custom_fields,
        "include_attachments": bool(include_attachments),
        "max_attachments_per_issue": int(max_attachments_per_issue),
        "max_total_attachments": int(max_total_attachments),
        "include_linked_artifacts": bool(include_linked_artifacts),
        "max_linked_artifacts_per_issue": int(max_linked_artifacts_per_issue),
        "max_total_linked_artifacts": int(max_total_linked_artifacts),
        "parser_backend": cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto",
        "chunk_strategy": cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "jira_ticket",
        "pipeline": cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None,
        "access": access,
        "source_acl_mode": source_acl_mode,
        "source_acl_fallback_mode": source_acl_fallback_mode,
        "has_manual_access_override": has_manual_access_override,
        "enable_source_acl": bool(source_acl_mode == "inherit" and not has_manual_access_override),
        "extra_jql": str(cfg.get("jql") or "").strip(),
        "user_agent": user_agent,
        "auth_headers": auth_headers,
        "api_base": _jira_api_base_url(base_url),
        "search_url": f"{_jira_api_base_url(base_url)}/search",
        "headers": headers,
    }


def _build_jira_project_search_jql(
    *,
    project_key: str,
    extra_jql: str,
    effective_mode: str,
    cursor_last_modified: str,
) -> str:
    jql_parts = [f'project = "{project_key}"']
    if extra_jql:
        jql_parts.append(f"({extra_jql})")
    if effective_mode == "incremental" and cursor_last_modified:
        after = _resolve_connectors_helper("_jira_jql_updated_after")(cursor_last_modified)
        if after:
            jql_parts.append(f'updated >= "{after}"')
    return " AND ".join(jql_parts) + " ORDER BY updated ASC"


def _build_jira_issue_info(*, base_url: str, issue: dict[str, Any]) -> dict[str, str | None]:
    issue_key = str(issue.get("key") or "").strip() if isinstance(issue, dict) else ""
    issue_id = str(issue.get("id") or "").strip() if isinstance(issue, dict) else ""
    issue_url = _resolve_connectors_helper("_jira_issue_url")(base_url=base_url, issue_key=issue_key)
    updated = _resolve_connectors_helper("_jira_extract_issue_updated")(issue if isinstance(issue, dict) else {}) or None
    return {
        "issue_id": issue_id,
        "issue_key": issue_key,
        "issue_url": issue_url,
        "updated": updated,
    }


def _resolve_jira_issue_acl(
    db: Session,
    *,
    tenant_id: UUID,
    run_id: UUID,
    requested_by: str,
    run: ConnectorRun,
    issue: dict[str, Any],
    issue_info: dict[str, str | None],
    settings_map: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int]:
    effective_access = settings_map.get("access")
    acl_provenance: dict[str, Any] | None = None
    issue_url = str(issue_info.get("issue_url") or "").strip()

    if not settings_map.get("enable_source_acl") or not issue_url:
        return (effective_access if isinstance(effective_access, dict) else None), None, 0

    restricted, ext_ids = _resolve_connectors_helper("_jira_issue_acl_principal_keys")(
        issue if isinstance(issue, dict) else {},
        include_comments=bool(settings_map.get("include_comments")),
        max_comments=int(settings_map.get("max_comments_per_issue") or 0),
    )
    if not restricted:
        return (effective_access if isinstance(effective_access, dict) else None), None, 0

    mapped_groups: set[UUID] = set()
    fallback_used = False
    try:
        mapped_groups = set(
            _resolve_connectors_helper("_resolve_tenant_group_ids_by_external_id")(
                db,
                tenant_id=tenant_id,
                external_ids=ext_ids,
            )
            or set()
        )
        if mapped_groups:
            ordered = sorted(mapped_groups, key=lambda value: str(value))
            effective_access = {
                "mode": "partial_members",
                "partial_group_list": [str(group_id) for group_id in ordered],
            }
        else:
            effective_access = {"mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members")}
            fallback_used = True
    except Exception:
        effective_access = {"mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members")}
        fallback_used = True

    with contextlib.suppress(Exception):
        from app.services.document_acl_provenance_service import build_document_acl_provenance

        acl_provenance = build_document_acl_provenance(
            connector_id="jira_project",
            connector_run_id=str(run_id),
            effective_access=effective_access,
            source_acl_mode=str(settings_map.get("source_acl_mode") or "disabled"),
            source_acl_fallback_mode=str(settings_map.get("source_acl_fallback_mode") or "partial_members"),
            source_principal_external_ids=ext_ids,
            mapped_group_ids=mapped_groups,
            fallback_used=fallback_used,
            restricted=restricted,
        )

    updated_existing = int(
        _resolve_connectors_helper("_delta_sync_jira_documents_acl_by_issue_url")(
            db,
            tenant_id=tenant_id,
            dataset_id=run.dataset_id,
            base_url=str(settings_map.get("base_url") or ""),
            project_key=str(settings_map.get("project_key") or ""),
            issue_url=issue_url,
            requested_by=requested_by,
            access=effective_access,
            acl_provenance=acl_provenance,
        )
    )
    return (effective_access if isinstance(effective_access, dict) else None), acl_provenance, updated_existing


def _jira_attachment_limits(cfg: dict) -> tuple[bool, int, int]:
    raw = cfg if isinstance(cfg, dict) else {}
    include = bool(raw.get("include_attachments", False))

    per_issue = int(raw.get("max_attachments_per_issue") or 10)
    per_issue = max(1, min(per_issue, 50))

    total = int(raw.get("max_total_attachments") or 200)
    total = max(1, min(total, 2000))

    return include, per_issue, total


def _jira_linked_artifact_limits(cfg: dict) -> tuple[bool, int, int]:
    raw = cfg if isinstance(cfg, dict) else {}
    include = bool(raw.get("include_linked_artifacts", False))

    per_issue = int(raw.get("max_linked_artifacts_per_issue") or 10)
    per_issue = max(1, min(per_issue, 50))

    total = int(raw.get("max_total_linked_artifacts") or 200)
    total = max(1, min(total, 2000))

    return include, per_issue, total


def _jira_extract_attachments(issue: dict, *, limit: int) -> list[dict[str, str]]:
    if not isinstance(issue, dict):
        return []

    lim = int(limit or 0)
    if lim <= 0:
        lim = 10_000

    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    items = fields.get("attachment") if isinstance(fields.get("attachment"), list) else []
    out: list[dict[str, str]] = []

    for raw in items:
        if len(out) >= lim:
            break
        if not isinstance(raw, dict):
            continue

        attachment_id = str(raw.get("id") or "").strip()
        if not attachment_id:
            continue

        filename = str(raw.get("filename") or raw.get("title") or raw.get("name") or "").strip()
        if not filename:
            filename = f"jira-attachment-{attachment_id}"

        download_url = str(raw.get("content") or raw.get("downloadUrl") or raw.get("download_url") or "").strip()
        if not download_url:
            continue

        out.append(
            {
                "attachment_id": attachment_id,
                "filename": filename,
                "download_url": download_url,
            }
        )

    return out


def _jira_extract_urls_from_text(value: object, *, limit: int) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []

    lim = int(limit or 0)
    if lim <= 0:
        lim = 10_000

    url_re = re.compile(r"https?://[^\s<>\")\]]+", flags=re.IGNORECASE)
    out: list[str] = []
    seen: set[str] = set()
    for m in url_re.finditer(text):
        url = str(m.group(0) or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= lim:
            break
    return out


def _jira_extract_urls_from_adf(value: object, *, limit: int) -> list[str]:
    lim = int(limit or 0)
    if lim <= 0:
        lim = 10_000

    out: list[str] = []
    seen: set[str] = set()

    def _push(raw: object) -> None:
        if len(out) >= lim:
            return
        url = str(raw or "").strip()
        if not url:
            return
        if not _resolve_connectors_helper("_is_http_or_https_url")(url):
            return
        if url in seen:
            return
        seen.add(url)
        out.append(url)

    def _walk(node: object, *, depth: int = 0) -> None:
        if len(out) >= lim or depth > 60:
            return
        if node is None:
            return
        if isinstance(node, str):
            for u in _jira_extract_urls_from_text(node, limit=lim - len(out)):
                _push(u)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item, depth=depth + 1)
            return
        if not isinstance(node, dict):
            return

        node_type = str(node.get("type") or "").strip().lower()
        if node_type == "text":
            marks = node.get("marks") if isinstance(node.get("marks"), list) else []
            for mark in marks:
                if not isinstance(mark, dict):
                    continue
                if str(mark.get("type") or "").strip().lower() != "link":
                    continue
                attrs = mark.get("attrs") if isinstance(mark.get("attrs"), dict) else {}
                _push(attrs.get("href"))
        elif node_type == "inlinecard":
            attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
            _push(attrs.get("url"))

        content = node.get("content")
        items = content if isinstance(content, list) else []
        for item in items:
            _walk(item, depth=depth + 1)

    _walk(value)
    return out


def _jira_extract_linked_artifact_urls(issue: dict, *, include_comments: bool, max_comments: int, limit: int) -> list[str]:
    if not isinstance(issue, dict):
        return []

    lim = int(limit or 0)
    if lim <= 0:
        lim = 10_000

    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    out: list[str] = []
    seen: set[str] = set()

    def _extend(urls: list[str]) -> None:
        nonlocal out
        for url in urls:
            if len(out) >= lim:
                return
            u = str(url or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            out.append(u)

    desc = fields.get("description")
    if _jira_adf_is_doc(desc):
        _extend(_jira_extract_urls_from_adf(desc, limit=lim - len(out)))
    else:
        _extend(_jira_extract_urls_from_text(desc, limit=lim - len(out)))

    if include_comments:
        comments_obj = fields.get("comment") if isinstance(fields.get("comment"), dict) else {}
        comment_items = comments_obj.get("comments") if isinstance(comments_obj.get("comments"), list) else []
        lim_comments = max(0, int(max_comments or 0))
        for comment in comment_items[:lim_comments]:
            if len(out) >= lim:
                break
            if not isinstance(comment, dict):
                continue
            body = comment.get("body")
            if _jira_adf_is_doc(body):
                _extend(_jira_extract_urls_from_adf(body, limit=lim - len(out)))
            else:
                _extend(_jira_extract_urls_from_text(body, limit=lim - len(out)))

    out_sorted = sorted(out)
    return out_sorted[:lim]


def _jira_attachment_connector_metadata(
    *,
    base_url: str,
    project_key: str,
    issue_id: str | None,
    issue_key: str | None,
    issue_url: str,
    attachment_id: str,
    filename: str,
    download_url: str,
    run_id: str,
    mode: str,
) -> dict[str, Any]:
    return {
        "connector_id": "jira_project",
        "doc_kind": "attachment",
        "base_url": str(base_url or "").strip(),
        "project_key": str(project_key or "").strip().upper(),
        "issue_id": (str(issue_id or "").strip() or None),
        "issue_key": (str(issue_key or "").strip() or None),
        "issue_url": str(issue_url or "").strip(),
        "attachment_id": str(attachment_id or "").strip(),
        "filename": str(filename or "").strip(),
        "download_url": str(download_url or "").strip(),
        "run_id": str(run_id or "").strip(),
        "mode": str(mode or "").strip(),
    }


def _jira_linked_artifact_connector_metadata(
    *,
    base_url: str,
    project_key: str,
    issue_id: str | None,
    issue_key: str | None,
    issue_url: str,
    link_url: str,
    run_id: str,
    mode: str,
) -> dict[str, Any]:
    return {
        "connector_id": "jira_project",
        "doc_kind": "linked_artifact",
        "base_url": str(base_url or "").strip(),
        "project_key": str(project_key or "").strip().upper(),
        "issue_id": (str(issue_id or "").strip() or None),
        "issue_key": (str(issue_key or "").strip() or None),
        "issue_url": str(issue_url or "").strip(),
        "link_url": str(link_url or "").strip(),
        "run_id": str(run_id or "").strip(),
        "mode": str(mode or "").strip(),
    }


def _jira_should_send_auth_headers(*, base_url: str, url: str) -> bool:
    base = str(base_url or "").strip()
    target = str(url or "").strip()
    if not base or not target:
        return False
    try:
        b = urlparse(base)
        u = urlparse(target)
    except Exception:
        return False
    if not b.scheme or not b.netloc or not u.scheme or not u.netloc:
        return False
    if str(u.scheme or "").lower() not in {"http", "https"}:
        return False
    return str(b.netloc).lower() == str(u.netloc).lower()


def _patch_jira_linked_artifact_document_metadata(
    db: Session,
    *,
    link_doc: Any,
    run: ConnectorRun,
    issue_info: dict[str, str | None],
    link_url: str,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
) -> None:
    meta_link = dict(getattr(link_doc, "doc_metadata", None) or {})
    updated = str(issue_info.get("updated") or "").strip()
    issue_id = str(issue_info.get("issue_id") or "").strip() or None
    issue_key = str(issue_info.get("issue_key") or "").strip() or None
    issue_url = str(issue_info.get("issue_url") or "").strip()

    if updated:
        lm_iso = _resolve_connectors_helper("_normalize_datetime_utc_iso")(updated) or updated
        meta_link["source_last_modified_at"] = lm_iso
        meta_link["source_last_modified_source"] = JIRA_UPDATED_SOURCE
        meta_link["source_last_modified_raw"] = meta_link.get("source_last_modified_raw") or updated
    if isinstance(acl_provenance, dict):
        meta_link["acl_provenance"] = dict(acl_provenance)
    meta_link["connector"] = _jira_linked_artifact_connector_metadata(
        base_url=str(settings_map.get("base_url") or ""),
        project_key=str(settings_map.get("project_key") or ""),
        issue_id=issue_id,
        issue_key=issue_key,
        issue_url=issue_url,
        link_url=link_url,
        run_id=str(run.id),
        mode=str(settings_map.get("effective_mode") or ""),
    )
    link_doc.doc_metadata = meta_link
    _resolve_connectors_helper("_apply_connector_identity_metadata")(
        doc=link_doc,
        run=run,
        connector_id="jira_project",
        source_ref=link_url,
        source_id=link_url,
    )
    db.commit()


async def _ingest_single_jira_linked_artifact(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    issue_info: dict[str, str | None],
    link_url: str,
    effective_access: dict[str, Any] | None,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
) -> UUID:
    fetch_headers = (
        settings_map.get("auth_headers") or None
        if _jira_should_send_auth_headers(
            base_url=str(settings_map.get("base_url") or ""),
            url=link_url,
        )
        else None
    )
    link_body = _resolve_connectors_helper("UrlUploadRequest")(
        url=link_url,
        dataset_id=run.dataset_id,
        filename=None,
        fetch_headers=fetch_headers,
        user_agent=settings_map.get("user_agent"),
        parser_backend=str(settings_map.get("parser_backend") or "auto"),
        chunk_strategy=str(settings_map.get("chunk_strategy") or "langchain_recursive"),
        pipeline=settings_map.get("pipeline"),
    )
    link_doc = await _resolve_connectors_helper("_ingest_url_upload_request")(
        background_tasks=None,
        body=link_body,
        tenant_id=tenant_id,
        account_id=requested_by,
        db=db,
    )
    _resolve_connectors_helper("_apply_document_access_from_config")(
        db,
        tenant_id=tenant_id,
        requested_by=requested_by,
        doc=link_doc,
        access=effective_access,
        connector_id="jira_project",
    )

    with contextlib.suppress(Exception):
        _patch_jira_linked_artifact_document_metadata(
            db,
            link_doc=link_doc,
            run=run,
            issue_info=issue_info,
            link_url=link_url,
            acl_provenance=acl_provenance,
            settings_map=settings_map,
        )

    db.add(
        ConnectorRunDocument(
            tenant_id=tenant_id,
            run_id=run.id,
            document_id=link_doc.id,
            source_ref=link_url[:1000] or None,
            status="created",
        )
    )
    return link_doc.id


def _jira_project_run_cancelled(db: Session, *, run: ConnectorRun) -> bool:
    with contextlib.suppress(Exception):
        db.refresh(run)
    return str(run.status or "").lower() == "cancelled"


async def _ingest_jira_issue_linked_artifacts(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    issue: dict[str, Any],
    issue_info: dict[str, str | None],
    effective_access: dict[str, Any] | None,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
    progress: dict[str, Any],
) -> dict[str, Any]:
    issue_url = str(issue_info.get("issue_url") or "").strip()
    if (
        not settings_map.get("include_linked_artifacts")
        or not issue_url
        or int(progress.get("linked_artifacts_processed") or 0) >= int(settings_map.get("max_total_linked_artifacts") or 0)
        or _resolve_connectors_helper("_jira_project_run_cancelled")(db, run=run)
    ):
        return {
            "linked_artifacts_processed": 0,
            "linked_artifacts_created": 0,
            "failed": 0,
            "created_doc_ids": [],
            "removed_linked_artifact_documents_disabled": 0,
        }

    remaining_total = int(settings_map.get("max_total_linked_artifacts") or 0) - int(
        progress.get("linked_artifacts_processed") or 0
    )
    per_issue_limit_eff = int(min(int(settings_map.get("max_linked_artifacts_per_issue") or 0), max(0, remaining_total)))
    if per_issue_limit_eff <= 0:
        return {
            "linked_artifacts_processed": 0,
            "linked_artifacts_created": 0,
            "failed": 0,
            "created_doc_ids": [],
            "removed_linked_artifact_documents_disabled": 0,
        }

    extract_limit = per_issue_limit_eff + 1
    urls = _resolve_connectors_helper("_jira_extract_linked_artifact_urls")(
        issue if isinstance(issue, dict) else {},
        include_comments=bool(settings_map.get("include_comments")),
        max_comments=int(settings_map.get("max_comments_per_issue") or 0),
        limit=extract_limit,
    )
    linked_listing_complete = bool(len(urls) <= per_issue_limit_eff)
    urls = urls[:per_issue_limit_eff]

    created_doc_ids: list[UUID] = []
    linked_artifacts_processed = 0
    linked_artifacts_created = 0
    failed = 0
    seen_link_urls: set[str] = set()

    for link_url in urls:
        if (int(progress.get("linked_artifacts_processed") or 0) + linked_artifacts_processed) >= int(
            settings_map.get("max_total_linked_artifacts") or 0
        ):
            linked_listing_complete = False
            break
        if _resolve_connectors_helper("_jira_project_run_cancelled")(db, run=run):
            linked_listing_complete = False
            break

        link_url = str(link_url or "").strip()
        if not link_url or link_url == issue_url or not _resolve_connectors_helper("_is_http_or_https_url")(link_url):
            continue

        seen_link_urls.add(link_url)
        linked_artifacts_processed += 1

        try:
            doc_id = await _resolve_connectors_helper("_ingest_single_jira_linked_artifact")(
                db,
                run=run,
                tenant_id=tenant_id,
                requested_by=requested_by,
                issue_info=issue_info,
                link_url=link_url,
                effective_access=effective_access,
                acl_provenance=acl_provenance,
                settings_map=settings_map,
            )
            created_doc_ids.append(doc_id)
            linked_artifacts_created += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            run.stats = _resolve_connectors_helper("_append_connector_error")(
                dict(run.stats or {}),
                url=(link_url or "jira_linked_artifact"),
                exc=exc,
            )

    removed_linked_artifact_documents_disabled = 0
    if linked_listing_complete:
        removed_linked_artifact_documents_disabled = int(
            _resolve_connectors_helper("_soft_disable_jira_linked_artifact_documents_missing_from_issue")(
                db,
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                base_url=str(settings_map.get("base_url") or ""),
                project_key=str(settings_map.get("project_key") or ""),
                issue_url=issue_url,
                seen_link_urls=seen_link_urls,
            )
        )

    return {
        "linked_artifacts_processed": linked_artifacts_processed,
        "linked_artifacts_created": linked_artifacts_created,
        "failed": failed,
        "created_doc_ids": created_doc_ids,
        "removed_linked_artifact_documents_disabled": removed_linked_artifact_documents_disabled,
    }


def _patch_jira_attachment_document_metadata(
    db: Session,
    *,
    att_doc: Any,
    run: ConnectorRun,
    issue_info: dict[str, str | None],
    attachment_ref: dict[str, str],
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
) -> None:
    attachment_id = str(attachment_ref.get("attachment_id") or "").strip()
    filename = str(attachment_ref.get("filename") or "").strip()
    download_url = str(attachment_ref.get("download_url") or "").strip()
    meta_att = dict(getattr(att_doc, "doc_metadata", None) or {})
    updated = str(issue_info.get("updated") or "").strip()
    issue_id = str(issue_info.get("issue_id") or "").strip() or None
    issue_key = str(issue_info.get("issue_key") or "").strip() or None
    issue_url = str(issue_info.get("issue_url") or "").strip()

    if updated:
        lm_iso = _resolve_connectors_helper("_normalize_datetime_utc_iso")(updated) or updated
        meta_att["source_last_modified_at"] = lm_iso
        meta_att["source_last_modified_source"] = JIRA_UPDATED_SOURCE
        meta_att["source_last_modified_raw"] = meta_att.get("source_last_modified_raw") or updated
    if isinstance(acl_provenance, dict):
        meta_att["acl_provenance"] = dict(acl_provenance)
    meta_att["connector"] = _jira_attachment_connector_metadata(
        base_url=str(settings_map.get("base_url") or ""),
        project_key=str(settings_map.get("project_key") or ""),
        issue_id=issue_id,
        issue_key=issue_key,
        issue_url=issue_url,
        attachment_id=attachment_id,
        filename=filename,
        download_url=download_url,
        run_id=str(run.id),
        mode=str(settings_map.get("effective_mode") or ""),
    )
    att_doc.doc_metadata = meta_att
    _resolve_connectors_helper("_apply_connector_identity_metadata")(
        doc=att_doc,
        run=run,
        connector_id="jira_project",
        source_ref=(attachment_id or download_url),
        source_id=(attachment_id or download_url),
    )
    db.commit()


async def _ingest_single_jira_attachment(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    issue_info: dict[str, str | None],
    attachment_ref: dict[str, str],
    effective_access: dict[str, Any] | None,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
) -> UUID:
    attachment_id = str(attachment_ref.get("attachment_id") or "").strip()
    filename = str(attachment_ref.get("filename") or "").strip()
    download_url = str(attachment_ref.get("download_url") or "").strip()
    att_body = _resolve_connectors_helper("UrlUploadRequest")(
        url=download_url,
        dataset_id=run.dataset_id,
        filename=filename,
        fetch_headers=settings_map.get("auth_headers") or None,
        user_agent=settings_map.get("user_agent"),
        parser_backend=str(settings_map.get("parser_backend") or "auto"),
        chunk_strategy=str(settings_map.get("chunk_strategy") or "langchain_recursive"),
        pipeline=settings_map.get("pipeline"),
    )
    att_doc = await _resolve_connectors_helper("_ingest_url_upload_request")(
        background_tasks=None,
        body=att_body,
        tenant_id=tenant_id,
        account_id=requested_by,
        db=db,
    )
    _resolve_connectors_helper("_apply_document_access_from_config")(
        db,
        tenant_id=tenant_id,
        requested_by=requested_by,
        doc=att_doc,
        access=effective_access,
        connector_id="jira_project",
    )

    with contextlib.suppress(Exception):
        _patch_jira_attachment_document_metadata(
            db,
            att_doc=att_doc,
            run=run,
            issue_info=issue_info,
            attachment_ref=attachment_ref,
            acl_provenance=acl_provenance,
            settings_map=settings_map,
        )

    db.add(
        ConnectorRunDocument(
            tenant_id=tenant_id,
            run_id=run.id,
            document_id=att_doc.id,
            source_ref=(attachment_id or download_url)[:1000] or None,
            status="created",
        )
    )
    return att_doc.id


async def _ingest_jira_issue_attachments(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    issue: dict[str, Any],
    issue_info: dict[str, str | None],
    effective_access: dict[str, Any] | None,
    acl_provenance: dict[str, Any] | None,
    settings_map: dict[str, Any],
    progress: dict[str, Any],
) -> dict[str, Any]:
    issue_url = str(issue_info.get("issue_url") or "").strip()
    if (
        not settings_map.get("include_attachments")
        or not issue_url
        or int(progress.get("attachments_processed") or 0) >= int(settings_map.get("max_total_attachments") or 0)
        or _resolve_connectors_helper("_jira_project_run_cancelled")(db, run=run)
    ):
        return {
            "attachments_processed": 0,
            "attachments_created": 0,
            "failed": 0,
            "created_doc_ids": [],
            "removed_attachment_documents_disabled": 0,
        }

    remaining_total = int(settings_map.get("max_total_attachments") or 0) - int(progress.get("attachments_processed") or 0)
    per_issue_limit_eff = int(min(int(settings_map.get("max_attachments_per_issue") or 0), max(0, remaining_total)))
    if per_issue_limit_eff <= 0:
        return {
            "attachments_processed": 0,
            "attachments_created": 0,
            "failed": 0,
            "created_doc_ids": [],
            "removed_attachment_documents_disabled": 0,
        }

    fields = issue.get("fields") if isinstance(issue, dict) and isinstance(issue.get("fields"), dict) else {}
    raw_attachments = fields.get("attachment") if isinstance(fields.get("attachment"), list) else []
    attachment_listing_complete = bool(per_issue_limit_eff >= len(raw_attachments))
    attachment_refs = _resolve_connectors_helper("_jira_extract_attachments")(
        issue if isinstance(issue, dict) else {},
        limit=per_issue_limit_eff,
    )

    attachments_processed = 0
    attachments_created = 0
    failed = 0
    created_doc_ids: list[UUID] = []
    seen_attachment_urls: set[str] = set()

    for attachment_ref in attachment_refs:
        if (int(progress.get("attachments_processed") or 0) + attachments_processed) >= int(
            settings_map.get("max_total_attachments") or 0
        ):
            attachment_listing_complete = False
            break
        if _resolve_connectors_helper("_jira_project_run_cancelled")(db, run=run):
            attachment_listing_complete = False
            break

        attachment_id = str(attachment_ref.get("attachment_id") or "").strip()
        filename = str(attachment_ref.get("filename") or "").strip()
        download_url = str(attachment_ref.get("download_url") or "").strip()
        attachments_processed += 1

        if not attachment_id or not download_url:
            continue
        seen_attachment_urls.add(download_url)

        ext = Path(filename).suffix.lower()
        if ext and ext not in _resolve_connectors_attr("settings").allowed_extensions_list:
            continue

        try:
            doc_id = await _resolve_connectors_helper("_ingest_single_jira_attachment")(
                db,
                run=run,
                tenant_id=tenant_id,
                requested_by=requested_by,
                issue_info=issue_info,
                attachment_ref=attachment_ref,
                effective_access=effective_access,
                acl_provenance=acl_provenance,
                settings_map=settings_map,
            )
            created_doc_ids.append(doc_id)
            attachments_created += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            run.stats = _resolve_connectors_helper("_append_connector_error")(
                dict(run.stats or {}),
                url=(download_url or attachment_id),
                exc=exc,
            )

    removed_attachment_documents_disabled = 0
    if attachment_listing_complete:
        removed_attachment_documents_disabled = int(
            _resolve_connectors_helper("_soft_disable_jira_attachment_documents_missing_from_issue")(
                db,
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                base_url=str(settings_map.get("base_url") or ""),
                project_key=str(settings_map.get("project_key") or ""),
                issue_url=issue_url,
                seen_attachment_urls=seen_attachment_urls,
            )
        )

    return {
        "attachments_processed": attachments_processed,
        "attachments_created": attachments_created,
        "failed": failed,
        "created_doc_ids": created_doc_ids,
        "removed_attachment_documents_disabled": removed_attachment_documents_disabled,
    }


def _initialize_jira_project_run_stats(*, run: ConnectorRun, settings_map: dict[str, Any]) -> dict[str, Any]:
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": settings_map.get("effective_mode"),
            "project_key": settings_map.get("project_key"),
            "base_url": settings_map.get("base_url"),
            "max_issues": int(settings_map.get("max_issues") or 0),
            "page_size": int(settings_map.get("page_size") or 0),
            "include_comments": bool(settings_map.get("include_comments")),
            "max_comments_per_issue": int(settings_map.get("max_comments_per_issue") or 0),
            "include_attachments": bool(settings_map.get("include_attachments")),
            "max_attachments_per_issue": int(settings_map.get("max_attachments_per_issue") or 0),
            "max_total_attachments": int(settings_map.get("max_total_attachments") or 0),
            "include_linked_artifacts": bool(settings_map.get("include_linked_artifacts")),
            "max_linked_artifacts_per_issue": int(settings_map.get("max_linked_artifacts_per_issue") or 0),
            "max_total_linked_artifacts": int(settings_map.get("max_total_linked_artifacts") or 0),
            "processed_issues": 0,
            "processed_attachments": 0,
            "cursor": 0,
            "created": 0,
            "created_attachments": 0,
            "processed_linked_artifacts": 0,
            "created_linked_artifacts": 0,
            "removed_linked_artifact_documents_disabled": 0,
            "failed": 0,
            "skipped_boundary_duplicates": 0,
            "failed_urls": [],
            "errors": [],
            "error_groups": [],
            "removed_issues_reconciled": 0,
            "removed_documents_disabled": 0,
            "removed_attachment_documents_disabled": 0,
        }
    )
    if settings_map.get("cursor_last_modified"):
        stats["cursor_in"] = settings_map.get("cursor_last_modified")
    return stats


def _persist_jira_project_progress(
    db: Session,
    *,
    run: ConnectorRun,
    progress: dict[str, Any],
) -> None:
    stats = dict(run.stats or {})
    stats.update(
        {
            "processed_issues": int(progress.get("processed") or 0),
            "processed_attachments": int(progress.get("attachments_processed") or 0),
            "processed_linked_artifacts": int(progress.get("linked_artifacts_processed") or 0),
            "cursor": int(progress.get("processed") or 0),
            "created": int(progress.get("created") or 0),
            "created_attachments": int(progress.get("attachments_created") or 0),
            "created_linked_artifacts": int(progress.get("linked_artifacts_created") or 0),
            "failed": int(progress.get("failed") or 0),
            "skipped_boundary_duplicates": int(progress.get("skipped_boundary_duplicates") or 0),
            "document_ids": [str(doc_id) for doc_id in (progress.get("created_doc_ids") or [])],
            "acl_delta_sync_updated_documents": int(progress.get("delta_acl_docs_updated") or 0),
            "acl_delta_sync_updated_sources": int(progress.get("delta_acl_sources_updated") or 0),
            "removed_issues_reconciled": int(progress.get("removed_issues_reconciled") or 0),
            "removed_documents_disabled": int(progress.get("removed_documents_disabled") or 0),
            "removed_attachment_documents_disabled": int(progress.get("removed_attachment_documents_disabled") or 0),
            "removed_linked_artifact_documents_disabled": int(progress.get("removed_linked_artifact_documents_disabled") or 0),
        }
    )
    if progress.get("last_modified_seen"):
        stats["last_modified"] = progress.get("last_modified_seen")
        stats["last_modified_ids"] = sorted(progress.get("last_modified_ids_seen") or set())
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    db.commit()


def _finalize_cancelled_jira_project_run(
    db: Session,
    *,
    run: ConnectorRun,
) -> None:
    if run.finished_at is None:
        run.finished_at = _resolve_connectors_helper("_now")()
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(dict(run.stats or {}))
    db.commit()
    with contextlib.suppress(Exception):
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _finalize_jira_project_run(
    db: Session,
    *,
    run: ConnectorRun,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
    settings_map: dict[str, Any],
    progress: dict[str, Any],
    observed_issue_urls: set[str],
    listing_complete: bool,
) -> None:
    if str(settings_map.get("effective_mode") or "") == "full" and run.dataset_id and listing_complete:
        try:
            removed_issues_reconciled, removed_documents_disabled = _resolve_connectors_helper(
                "_soft_disable_jira_documents_missing_from_full_sync"
            )(
                db,
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                base_url=str(settings_map.get("base_url") or ""),
                project_key=str(settings_map.get("project_key") or ""),
                seen_issue_urls=observed_issue_urls,
            )
            progress["removed_issues_reconciled"] = int(removed_issues_reconciled)
            progress["removed_documents_disabled"] = int(removed_documents_disabled)
        except Exception as exc:  # noqa: BLE001
            run.stats = _resolve_connectors_helper("_finalize_connector_stats")(
                _resolve_connectors_helper("_append_connector_error")(
                    dict(run.stats or {}),
                    url=f"jira://{str(settings_map.get('project_key') or '')}",
                    exc=exc,
                )
            )
            db.commit()

    stats = dict(run.stats or {})
    stats.update(
        {
            "document_ids": [str(doc_id) for doc_id in (progress.get("created_doc_ids") or [])],
            "acl_delta_sync_updated_documents": int(progress.get("delta_acl_docs_updated") or 0),
            "acl_delta_sync_updated_sources": int(progress.get("delta_acl_sources_updated") or 0),
            "removed_issues_reconciled": int(progress.get("removed_issues_reconciled") or 0),
            "removed_documents_disabled": int(progress.get("removed_documents_disabled") or 0),
            "processed_attachments": int(progress.get("attachments_processed") or 0),
            "created_attachments": int(progress.get("attachments_created") or 0),
            "removed_attachment_documents_disabled": int(progress.get("removed_attachment_documents_disabled") or 0),
            "processed_linked_artifacts": int(progress.get("linked_artifacts_processed") or 0),
            "created_linked_artifacts": int(progress.get("linked_artifacts_created") or 0),
            "removed_linked_artifact_documents_disabled": int(progress.get("removed_linked_artifact_documents_disabled") or 0),
            "skipped_boundary_duplicates": int(progress.get("skipped_boundary_duplicates") or 0),
        }
    )
    if progress.get("last_modified_seen"):
        stats["last_modified"] = progress.get("last_modified_seen")
        stats["last_modified_ids"] = sorted(progress.get("last_modified_ids_seen") or set())
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    run.finished_at = _resolve_connectors_helper("_now")()
    run.status = _resolve_connectors_helper("_connector_run_completion_status")(
        created=int(progress.get("created") or 0),
        failed=int(progress.get("failed") or 0),
    )
    if settings_map.get("enable_source_acl"):
        with contextlib.suppress(Exception):
            from app.services.audit_log_service import audit_log_event as audit_log_event_fn

            audit_log_event_fn(
                db,
                tenant_id=tenant_id,
                actor_id=requested_by,
                action="jira_project.source_acl.delta_sync",
                resource_type="connector_run",
                resource_id=str(run_id),
                details={
                    "dataset_id": str(run.dataset_id),
                    "connector_id": "jira_project",
                    "base_url": str(settings_map.get("base_url") or ""),
                    "project_key": str(settings_map.get("project_key") or ""),
                    "mode": str(settings_map.get("effective_mode") or ""),
                    "updated_documents": int(progress.get("delta_acl_docs_updated") or 0),
                    "updated_sources": int(progress.get("delta_acl_sources_updated") or 0),
                    "fallback_mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members"),
                },
            )
    db.commit()
    with contextlib.suppress(Exception):
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _persist_jira_project_skipped_boundary_duplicates(
    db: Session,
    *,
    run: ConnectorRun,
    skipped_boundary_duplicates: int,
) -> None:
    stats = dict(run.stats or {})
    stats["skipped_boundary_duplicates"] = int(skipped_boundary_duplicates)
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    db.commit()


async def _process_jira_project_issue(
    db: Session,
    *,
    run: ConnectorRun,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
    issue: object,
    base_url: str,
    project_key: str,
    cursor_last_modified: str,
    cursor_last_modified_ids: set[str],
    effective_mode: str,
    include_comments: bool,
    max_comments_per_issue: int,
    include_attachments: bool,
    max_attachments_per_issue: int,
    max_total_attachments: int,
    include_linked_artifacts: bool,
    max_linked_artifacts_per_issue: int,
    max_total_linked_artifacts: int,
    parser_backend: str,
    chunk_strategy: str,
    pipeline: object,
    access: object,
    user_agent: object,
    auth_headers: dict[str, str],
    enable_source_acl: bool,
    source_acl_mode: str,
    source_acl_fallback_mode: str,
    progress: dict[str, Any],
    observed_issue_urls: set[str],
) -> None:
    created = int(progress.get("created") or 0)
    failed = int(progress.get("failed") or 0)
    processed = int(progress.get("processed") or 0)
    created_doc_ids = list(progress.get("created_doc_ids") or [])
    delta_acl_docs_updated = int(progress.get("delta_acl_docs_updated") or 0)
    delta_acl_sources_updated = int(progress.get("delta_acl_sources_updated") or 0)
    last_modified_seen = progress.get("last_modified_seen")
    last_modified_ids_seen = set(progress.get("last_modified_ids_seen") or set())
    attachments_processed = int(progress.get("attachments_processed") or 0)
    attachments_created = int(progress.get("attachments_created") or 0)
    removed_attachment_documents_disabled = int(progress.get("removed_attachment_documents_disabled") or 0)
    linked_artifacts_processed = int(progress.get("linked_artifacts_processed") or 0)
    linked_artifacts_created = int(progress.get("linked_artifacts_created") or 0)
    removed_linked_artifact_documents_disabled = int(progress.get("removed_linked_artifact_documents_disabled") or 0)
    skipped_boundary_duplicates = int(progress.get("skipped_boundary_duplicates") or 0)

    issue_info = _build_jira_issue_info(
        base_url=base_url,
        issue=issue if isinstance(issue, dict) else {},
    )
    issue_key = str(issue_info.get("issue_key") or "")
    issue_id = str(issue_info.get("issue_id") or "")
    issue_url = str(issue_info.get("issue_url") or "")
    updated = str(issue_info.get("updated") or "")
    label = issue_url or issue_key or issue_id or "jira_issue"

    if effective_mode == "incremental" and _resolve_connectors_helper("_should_skip_timestamp_boundary_item")(
        item_id=issue_id,
        item_timestamp=updated,
        cursor_timestamp=cursor_last_modified,
        boundary_ids=cursor_last_modified_ids,
    ):
        skipped_boundary_duplicates += 1
        progress["skipped_boundary_duplicates"] = skipped_boundary_duplicates
        _persist_jira_project_skipped_boundary_duplicates(
            db,
            run=run,
            skipped_boundary_duplicates=skipped_boundary_duplicates,
        )
        return

    if updated:
        last_modified_seen, last_modified_ids_seen = _resolve_connectors_helper("_advance_timestamp_boundary")(
            last_timestamp=last_modified_seen,
            boundary_ids=last_modified_ids_seen,
            item_timestamp=updated,
            item_id=issue_id,
        )

    try:
        if not issue_url:
            raise ValueError("missing issue url")

        observed_issue_urls.add(issue_url)

        effective_access, acl_provenance, updated_existing = _resolve_connectors_helper("_resolve_jira_issue_acl")(
            db,
            tenant_id=tenant_id,
            run_id=run_id,
            requested_by=requested_by,
            run=run,
            issue=issue if isinstance(issue, dict) else {},
            issue_info=issue_info,
            settings_map={
                "access": access,
                "enable_source_acl": enable_source_acl,
                "include_comments": include_comments,
                "max_comments_per_issue": max_comments_per_issue,
                "source_acl_mode": source_acl_mode,
                "source_acl_fallback_mode": source_acl_fallback_mode,
                "base_url": base_url,
                "project_key": project_key,
            },
        )
        delta_acl_docs_updated += int(updated_existing)
        if updated_existing:
            delta_acl_sources_updated += 1

        filename = f"{issue_key}.html" if issue_key else "jira-issue.html"
        issue_html = _resolve_connectors_helper("_jira_render_issue_html")(
            base_url=base_url,
            issue=issue if isinstance(issue, dict) else {},
            include_comments=include_comments,
            max_comments=max_comments_per_issue,
        )
        if not issue_html.strip():
            raise ValueError("missing rendered issue html")

        html_body = _resolve_connectors_helper("LocalHtmlIngestRequest")(
            html=issue_html,
            source_url=issue_url,
            dataset_id=run.dataset_id,
            filename=filename,
            parser_backend=str(parser_backend),
            chunk_strategy=str(chunk_strategy),
            pipeline=pipeline,
        )
        doc = await _resolve_connectors_helper("_ingest_local_html_request")(
            background_tasks=None,
            body=html_body,
            tenant_id=tenant_id,
            account_id=requested_by,
            db=db,
            ingestion_kind="upload_url",
        )

        _resolve_connectors_helper("_apply_document_access_from_config")(
            db,
            tenant_id=tenant_id,
            requested_by=requested_by,
            doc=doc,
            access=effective_access,
            connector_id="jira_project",
        )

        with contextlib.suppress(Exception):
            meta0 = dict(getattr(doc, "doc_metadata", None) or {})
            if updated:
                lm_iso = _resolve_connectors_helper("_normalize_datetime_utc_iso")(updated) or updated
                meta0["source_last_modified_at"] = lm_iso
                meta0["source_last_modified_source"] = "connector:jira:updated"
                meta0["source_last_modified_raw"] = meta0.get("source_last_modified_raw") or updated
            if isinstance(acl_provenance, dict):
                meta0["acl_provenance"] = dict(acl_provenance)
            meta0["connector"] = {
                "connector_id": "jira_project",
                "base_url": base_url,
                "project_key": project_key,
                "issue_id": (issue_id or None),
                "issue_key": (issue_key or None),
                "issue_url": issue_url,
                "last_modified": (updated or None),
                "run_id": str(run.id),
                "mode": effective_mode,
            }
            doc.doc_metadata = meta0
            _resolve_connectors_helper("_apply_connector_identity_metadata")(
                doc=doc,
                run=run,
                connector_id="jira_project",
                source_ref=(issue_key or issue_id or issue_url),
                source_id=(issue_id or issue_key or issue_url),
            )
            db.commit()

        db.add(
            _resolve_connectors_helper("ConnectorRunDocument")(
                tenant_id=tenant_id,
                run_id=run.id,
                document_id=doc.id,
                source_ref=(issue_key or issue_id or issue_url)[:1000] or None,
                status="created",
            )
        )
        created += 1
        created_doc_ids.append(doc.id)

        linked_artifacts = await _resolve_connectors_helper("_ingest_jira_issue_linked_artifacts")(
            db,
            run=run,
            tenant_id=tenant_id,
            requested_by=requested_by,
            issue=issue if isinstance(issue, dict) else {},
            issue_info=issue_info,
            effective_access=effective_access,
            acl_provenance=acl_provenance,
            settings_map={
                "base_url": base_url,
                "project_key": project_key,
                "include_linked_artifacts": include_linked_artifacts,
                "max_total_linked_artifacts": max_total_linked_artifacts,
                "max_linked_artifacts_per_issue": max_linked_artifacts_per_issue,
                "include_comments": include_comments,
                "max_comments_per_issue": max_comments_per_issue,
                "auth_headers": auth_headers,
                "user_agent": user_agent,
                "parser_backend": parser_backend,
                "chunk_strategy": chunk_strategy,
                "pipeline": pipeline,
                "effective_mode": effective_mode,
            },
            progress={
                "linked_artifacts_processed": linked_artifacts_processed,
            },
        )
        linked_artifacts_processed += int(linked_artifacts.get("linked_artifacts_processed") or 0)
        linked_artifacts_created += int(linked_artifacts.get("linked_artifacts_created") or 0)
        created += int(linked_artifacts.get("linked_artifacts_created") or 0)
        failed += int(linked_artifacts.get("failed") or 0)
        created_doc_ids.extend(linked_artifacts.get("created_doc_ids") or [])
        removed_linked_artifact_documents_disabled += int(linked_artifacts.get("removed_linked_artifact_documents_disabled") or 0)

        attachments = await _resolve_connectors_helper("_ingest_jira_issue_attachments")(
            db,
            run=run,
            tenant_id=tenant_id,
            requested_by=requested_by,
            issue=issue if isinstance(issue, dict) else {},
            issue_info=issue_info,
            effective_access=effective_access,
            acl_provenance=acl_provenance,
            settings_map={
                "base_url": base_url,
                "project_key": project_key,
                "include_attachments": include_attachments,
                "max_total_attachments": max_total_attachments,
                "max_attachments_per_issue": max_attachments_per_issue,
                "auth_headers": auth_headers,
                "user_agent": user_agent,
                "parser_backend": parser_backend,
                "chunk_strategy": chunk_strategy,
                "pipeline": pipeline,
                "effective_mode": effective_mode,
            },
            progress={
                "attachments_processed": attachments_processed,
            },
        )
        attachments_processed += int(attachments.get("attachments_processed") or 0)
        attachments_created += int(attachments.get("attachments_created") or 0)
        created += int(attachments.get("attachments_created") or 0)
        failed += int(attachments.get("failed") or 0)
        created_doc_ids.extend(attachments.get("created_doc_ids") or [])
        removed_attachment_documents_disabled += int(attachments.get("removed_attachment_documents_disabled") or 0)
    except Exception as exc:  # noqa: BLE001
        failed += 1
        stats = dict(run.stats or {})
        stats = _resolve_connectors_helper("_append_connector_error")(stats, url=label, exc=exc)
        run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    finally:
        processed += 1
        progress.update(
            {
                "created": created,
                "failed": failed,
                "processed": processed,
                "created_doc_ids": created_doc_ids,
                "delta_acl_docs_updated": delta_acl_docs_updated,
                "delta_acl_sources_updated": delta_acl_sources_updated,
                "last_modified_seen": last_modified_seen,
                "last_modified_ids_seen": last_modified_ids_seen,
                "attachments_processed": attachments_processed,
                "attachments_created": attachments_created,
                "removed_attachment_documents_disabled": removed_attachment_documents_disabled,
                "linked_artifacts_processed": linked_artifacts_processed,
                "linked_artifacts_created": linked_artifacts_created,
                "removed_linked_artifact_documents_disabled": removed_linked_artifact_documents_disabled,
                "skipped_boundary_duplicates": skipped_boundary_duplicates,
            }
        )
        _resolve_connectors_helper("_persist_jira_project_progress")(db, run=run, progress=progress)


def _get_jira_project_run(db: Session, *, run_id: UUID, tenant_id: UUID) -> ConnectorRun | None:
    return (
        db.query(ConnectorRun)
        .options(selectinload(ConnectorRun.documents))
        .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
        .first()
    )


def _mark_jira_project_run_running(db: Session, *, run: ConnectorRun) -> None:
    run.status = "running"
    run.started_at = _resolve_connectors_helper("_now")()
    run.error_message = None
    run.stats = dict(run.stats or {})
    db.commit()
    db.refresh(run)


def _mark_jira_project_run_failed(db: Session, *, run_id: UUID, tenant_id: UUID, exc: Exception) -> None:
    with contextlib.suppress(Exception):
        run = (
            db.query(ConnectorRun)
            .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
            .first()
        )
        if run is None:
            return
        run.status = "failed"
        run.finished_at = _resolve_connectors_helper("_now")()
        run.error_message = str(exc)[:200]
        db.commit()
        with contextlib.suppress(Exception):
            _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _jira_project_search_params(
    *,
    jql: str,
    start_at: int,
    max_results: int,
    custom_fields: list[str],
) -> dict[str, Any]:
    fields = ",".join(
        [
            "summary",
            "description",
            "updated",
            "issuetype",
            "priority",
            "status",
            "labels",
            "comment",
            "security",
            "attachment",
            *custom_fields,
        ]
    )
    return {
        "jql": jql,
        "startAt": int(start_at),
        "maxResults": int(max_results),
        "fields": fields,
        "expand": "renderedFields",
    }


def _jira_project_parse_search_payload(payload: object) -> tuple[int | None, list[object]]:
    total_issues_available: int | None = None
    issues: list[object] = []

    if not isinstance(payload, dict):
        return total_issues_available, issues

    total_raw = payload.get("total")
    if isinstance(total_raw, (int, float)) and not isinstance(total_raw, bool):
        total_issues_available = max(0, int(total_raw))

    issues_raw = payload.get("issues")
    if isinstance(issues_raw, list):
        issues = issues_raw

    return total_issues_available, issues


async def _jira_project_fetch_issue_page(
    pool,
    *,
    search_url: str,
    headers: dict[str, str],
    jql: str,
    start_at: int,
    page_request_size: int,
    custom_fields: list[str],
) -> tuple[int | None, list[object]]:
    params = _jira_project_search_params(
        jql=jql,
        start_at=start_at,
        max_results=page_request_size,
        custom_fields=custom_fields,
    )
    resp = await _jira_request(pool, "GET", search_url, params=params, headers=headers)
    payload = resp.json() if resp is not None else {}
    return _jira_project_parse_search_payload(payload)


async def _process_jira_project_issues(
    db: Session,
    *,
    run: ConnectorRun,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
    settings_map: dict[str, Any],
) -> tuple[dict[str, Any], set[str], bool]:
    base_url = str(settings_map.get("base_url") or "")
    project_key = str(settings_map.get("project_key") or "")
    cursor_last_modified = str(settings_map.get("cursor_last_modified") or "")
    cursor_last_modified_ids = set(settings_map.get("cursor_last_modified_ids") or set())
    effective_mode = str(settings_map.get("effective_mode") or "")
    max_issues = int(settings_map.get("max_issues") or 0)
    page_size = int(settings_map.get("page_size") or 0)
    include_comments = bool(settings_map.get("include_comments"))
    max_comments_per_issue = int(settings_map.get("max_comments_per_issue") or 0)
    custom_fields = list(settings_map.get("custom_fields") or [])
    include_attachments = bool(settings_map.get("include_attachments"))
    max_attachments_per_issue = int(settings_map.get("max_attachments_per_issue") or 0)
    max_total_attachments = int(settings_map.get("max_total_attachments") or 0)
    include_linked_artifacts = bool(settings_map.get("include_linked_artifacts"))
    max_linked_artifacts_per_issue = int(settings_map.get("max_linked_artifacts_per_issue") or 0)
    max_total_linked_artifacts = int(settings_map.get("max_total_linked_artifacts") or 0)
    parser_backend = str(settings_map.get("parser_backend") or "auto")
    chunk_strategy = str(settings_map.get("chunk_strategy") or "jira_ticket")
    pipeline = settings_map.get("pipeline")
    access = settings_map.get("access")
    user_agent = settings_map.get("user_agent")
    auth_headers = dict(settings_map.get("auth_headers") or {})
    search_url = str(settings_map.get("search_url") or "")
    headers = dict(settings_map.get("headers") or {})
    jql = str(settings_map.get("jql") or "")

    source_acl_mode = str(settings_map.get("source_acl_mode") or "disabled")
    source_acl_fallback_mode = str(settings_map.get("source_acl_fallback_mode") or "partial_members")
    enable_source_acl = bool(settings_map.get("enable_source_acl"))

    progress: dict[str, Any] = {
        "created": 0,
        "failed": 0,
        "processed": 0,
        "created_doc_ids": [],
        "delta_acl_docs_updated": 0,
        "delta_acl_sources_updated": 0,
        "last_modified_seen": None,
        "last_modified_ids_seen": set(),
        "attachments_processed": 0,
        "attachments_created": 0,
        "removed_attachment_documents_disabled": 0,
        "linked_artifacts_processed": 0,
        "linked_artifacts_created": 0,
        "removed_linked_artifact_documents_disabled": 0,
        "skipped_boundary_duplicates": 0,
        "removed_issues_reconciled": 0,
        "removed_documents_disabled": 0,
    }
    observed_issue_urls: set[str] = set()
    listing_complete = False
    total_issues_available: int | None = None

    pool = _resolve_connectors_helper("get_http_client_pool")()
    start_at = 0

    while int(progress.get("processed") or 0) < max_issues:
        if _resolve_connectors_helper("_jira_project_run_cancelled")(db, run=run):
            break

        processed = int(progress.get("processed") or 0)
        page_request_size = int(min(page_size, max_issues - processed))
        page_total, issues = await _jira_project_fetch_issue_page(
            pool,
            search_url=search_url,
            headers=headers,
            jql=jql,
            start_at=start_at,
            page_request_size=page_request_size,
            custom_fields=custom_fields,
        )
        if page_total is not None:
            total_issues_available = page_total

        if not issues:
            if total_issues_available is None or start_at >= total_issues_available:
                listing_complete = True
            break

        for issue in issues:
            if int(progress.get("processed") or 0) >= max_issues:
                break
            if _resolve_connectors_helper("_jira_project_run_cancelled")(db, run=run):
                break

            await _resolve_connectors_helper("_process_jira_project_issue")(
                db,
                run=run,
                run_id=run_id,
                tenant_id=tenant_id,
                requested_by=requested_by,
                issue=issue,
                base_url=base_url,
                project_key=project_key,
                cursor_last_modified=cursor_last_modified,
                cursor_last_modified_ids=cursor_last_modified_ids,
                effective_mode=effective_mode,
                include_comments=include_comments,
                max_comments_per_issue=max_comments_per_issue,
                include_attachments=include_attachments,
                max_attachments_per_issue=max_attachments_per_issue,
                max_total_attachments=max_total_attachments,
                include_linked_artifacts=include_linked_artifacts,
                max_linked_artifacts_per_issue=max_linked_artifacts_per_issue,
                max_total_linked_artifacts=max_total_linked_artifacts,
                parser_backend=parser_backend,
                chunk_strategy=chunk_strategy,
                pipeline=pipeline,
                access=access,
                user_agent=user_agent,
                auth_headers=auth_headers,
                enable_source_acl=enable_source_acl,
                source_acl_mode=source_acl_mode,
                source_acl_fallback_mode=source_acl_fallback_mode,
                progress=progress,
                observed_issue_urls=observed_issue_urls,
            )

        start_at += int(len(issues))
        if total_issues_available is not None and start_at >= total_issues_available:
            listing_complete = True
        if len(issues) < page_request_size:
            listing_complete = True
            break

    return progress, observed_issue_urls, listing_complete


async def _execute_jira_project_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for jira_project connector.

    Flow:
    - List issues in a Jira project (full or incremental based on state/sync_mode)
    - Render each issue into a structured local HTML document
    - Apply best-effort Jira source ACL inheritance from security level / comment visibility
    """
    db = _resolve_connectors_helper("SessionLocal")()
    run: ConnectorRun | None = None
    try:
        run = _get_jira_project_run(db, run_id=run_id, tenant_id=tenant_id)
        if run is None:
            return
        if str(run.status or "").lower() in {"cancelled", "completed", "failed"}:
            return

        _mark_jira_project_run_running(db, run=run)

        settings_map = _resolve_connectors_helper("_build_jira_project_run_settings")(
            _resolve_connectors_helper("decrypt_connector_config_secrets")(dict(run.config or {}))
        )
        settings_map["jql"] = _resolve_connectors_helper("_build_jira_project_search_jql")(
            project_key=str(settings_map.get("project_key") or ""),
            extra_jql=str(settings_map.get("extra_jql") or ""),
            effective_mode=str(settings_map.get("effective_mode") or ""),
            cursor_last_modified=str(settings_map.get("cursor_last_modified") or ""),
        )

        run.stats = _resolve_connectors_helper("_finalize_connector_stats")(
            _resolve_connectors_helper("_initialize_jira_project_run_stats")(run=run, settings_map=settings_map)
        )
        db.commit()

        progress, observed_issue_urls, listing_complete = await _process_jira_project_issues(
            db,
            run=run,
            run_id=run_id,
            tenant_id=tenant_id,
            requested_by=requested_by,
            settings_map=settings_map,
        )
        if _resolve_connectors_helper("_jira_project_run_cancelled")(db, run=run):
            _resolve_connectors_helper("_finalize_cancelled_jira_project_run")(db, run=run)
            return

        _resolve_connectors_helper("_finalize_jira_project_run")(
            db,
            run=run,
            run_id=run_id,
            tenant_id=tenant_id,
            requested_by=requested_by,
            settings_map={
                "effective_mode": str(settings_map.get("effective_mode") or ""),
                "base_url": str(settings_map.get("base_url") or ""),
                "project_key": str(settings_map.get("project_key") or ""),
                "enable_source_acl": bool(settings_map.get("enable_source_acl")),
                "source_acl_fallback_mode": str(settings_map.get("source_acl_fallback_mode") or "partial_members"),
            },
            progress=progress,
            observed_issue_urls=observed_issue_urls,
            listing_complete=listing_complete,
        )
    except Exception as exc:  # noqa: BLE001
        _mark_jira_project_run_failed(db, run_id=run_id, tenant_id=tenant_id, exc=exc)
    finally:
        db.close()
