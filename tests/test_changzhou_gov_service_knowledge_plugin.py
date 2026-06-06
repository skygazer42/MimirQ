from __future__ import annotations

import json
from pathlib import Path

from langchain_core.documents import Document

from app.rag.pipeline_plugins.contracts import validate_documents_metadata
from app.rag.pipeline_plugins.registry import describe_plugin_dir, load_descriptor_stage_callable

PLUGIN_DIR = Path("plugins/pipelines/changzhou-gov-service-knowledge")


def test_changzhou_business_logic_stays_inside_plugin_package():
    plugin_helper = PLUGIN_DIR / "gov_service_items.py"
    platform_helper = Path("app/rag/pipeline_plugins/gov_service_items.py")
    plugin_entry = (PLUGIN_DIR / "plugin.py").read_text(encoding="utf-8")

    assert plugin_helper.is_file()
    assert not platform_helper.exists()
    assert "app.rag.pipeline_plugins.gov_service_items" not in plugin_entry


def _run_governance(doc: Document) -> list[Document]:
    descriptor = describe_plugin_dir(PLUGIN_DIR, require_test_report=False)
    func = load_descriptor_stage_callable(descriptor, "governance")
    return func([doc], {}, {"stage": "governance"})


def _run_chunk(documents: list[Document]) -> list[Document]:
    descriptor = describe_plugin_dir(PLUGIN_DIR, require_test_report=False)
    func = load_descriptor_stage_callable(descriptor, "chunk")
    return func(documents, {"max_record_chars": 1600}, {"stage": "chunk"})


def _run_kg(documents: list[Document]) -> list[dict]:
    descriptor = describe_plugin_dir(PLUGIN_DIR, require_test_report=False)
    func = load_descriptor_stage_callable(descriptor, "kg")
    return func(documents, {}, {"stage": "kg"})


def test_changzhou_plugin_sample_covers_representative_sections_and_metadata():
    raw_items = json.loads((PLUGIN_DIR / "sample.json").read_text(encoding="utf-8"))
    sample_docs = [
        Document(page_content=item["page_content"], metadata=dict(item.get("metadata") or {}))
        for item in raw_items
    ]
    records: list[Document] = []
    for doc in sample_docs:
        records.extend(_run_governance(doc))
    chunks = _run_chunk(records)
    events = _run_kg(chunks)

    sections = {record.metadata.get("knowledge_section") for record in records}
    metadata_keys = {key for record in records for key in (record.metadata or {})}
    entity_types = {
        entity.get("type")
        for event in events
        for entity in event.get("entities", [])
    }

    assert {
        "01政务服务事项知识",
        "02高效办成一件事",
        "03常州市常见问题",
        "04专题常见问答",
        "05业务部门常见问题",
        "06各区常见问题",
    }.issubset(sections)
    assert {"category_path", "applicable_area", "service_url", "source_sheet"}.issubset(metadata_keys)
    assert {"BusinessCategory", "Region", "Url", "SourceSheet"}.issubset(entity_types)


def test_changzhou_processing_templates_point_to_plugin_implementations():
    from app.services.governance_processing_scripts import list_builtin_processing_scripts

    payload = json.loads((PLUGIN_DIR / "processing_templates.json").read_text(encoding="utf-8"))
    templates = payload.get("templates")
    builtin_keys = {template.key for template in list_builtin_processing_scripts()}

    assert payload["schema"] == "mimirq.pipeline_plugin_processing_templates.v1"
    assert payload["plugin_id"] == "changzhou-gov-service-knowledge"
    assert isinstance(templates, list) and templates

    keys: set[str] = set()
    for template in templates:
        key = str(template.get("key") or "")
        assert key and key not in keys
        assert key not in builtin_keys
        keys.add(key)
        assert template.get("stage") in {"governance", "chunk", "kg"}
        refs = [template.get("implemented_by"), *list(template.get("related_implementations") or [])]
        for ref in refs:
            assert isinstance(ref, str) and ":" in ref
            rel_path, symbol = ref.split(":", 1)
            assert rel_path in {"plugin.py", "gov_service_items.py", "kg_builder.py"}
            assert symbol.isidentifier()
            source = (PLUGIN_DIR / rel_path).read_text(encoding="utf-8")
            assert f"def {symbol}" in source or f"{symbol} =" in source


def test_changzhou_plugin_governs_service_item_records():
    source = "/path/to/gov-service-knowledge/01政务服务事项知识/经开区事项清单.txt"
    text = """[事项名称：社会保障卡补卡]
行使层级：市级
办理形式：窗口办理,网上办理
办理地点：常州市政务服务中心
受理条件：已办理社会保障卡正式挂失的持卡人。
办理材料：1、居民身份证件（必要）
在线办理地址：**<http://cz.jszwfw.gov.cn/item?utm_source=x&webId=5>**
==##相似问法：补办社保卡、社保卡丢失##==
==##########==
[事项名称：学历公证]
行使层级：市级
办理形式：窗口办理
办理地点：公证处窗口
受理条件：申请人与事项有利害关系。
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)

    assert len(records) == 2
    assert records[0].metadata["knowledge_section"] == "01政务服务事项知识"
    assert records[0].metadata["gov_knowledge_type"] == "service_item"
    assert records[0].metadata["district"] == "经开区"
    assert records[0].metadata["service_name"] == "社会保障卡补卡"
    assert "utm_source" not in records[0].metadata["online_url"]
    assert chunks[0].metadata["chunk_kind"] == "service_item_full"


def test_changzhou_plugin_builds_service_item_kg_events():
    source = "/path/to/gov-service-knowledge/01政务服务事项知识/经开区事项清单.txt"
    text = """[事项名称：社会保障卡补卡]
行使层级：市级
办理形式：窗口办理,网上办理
办理地点：常州市政务服务中心
受理条件：已办理社会保障卡正式挂失的持卡人。
办理材料：1、居民身份证件（必要）
咨询方式：0519-12333
在线办理地址：**<http://cz.jszwfw.gov.cn/item?utm_source=x&webId=5>**
==##相似问法：补办社保卡、社保卡丢失##==
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)
    events = _run_kg(chunks)

    assert len(events) == 1
    assert events[0]["title"] == "政务事项：社会保障卡补卡"
    assert events[0]["references"]["chunk_kind"] == "service_item_full"
    assert events[0]["extra_data"]["gov_knowledge_type"] == "service_item"
    entity_pairs = {(item["type"], item["name"], item.get("role")) for item in events[0]["entities"]}
    assert ("ServiceItem", "社会保障卡补卡", "subject") in entity_pairs
    assert ("District", "经开区", "district") in entity_pairs
    assert ("Material", "居民身份证件（必要）", "material") in entity_pairs
    assert ("Channel", "网上办理", "service_channel") in entity_pairs


def test_changzhou_plugin_splits_overlong_service_field_chunks():
    source = "/path/to/gov-service-knowledge/01政务服务事项知识/经开区事项清单.txt"
    materials = "    ".join(
        f"{i}、第{i}项材料说明需要携带原件和复印件，并由申请人现场确认材料真实性（必要）"
        for i in range(1, 91)
    )
    text = f"""[事项名称：复杂材料事项]
行使层级：市级
办理形式：窗口办理
办理地点：常州市政务服务中心
受理条件：申请人符合办理条件。
办理材料：{materials}
咨询方式：0519-12345
==##########==
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)
    material_chunks = [chunk for chunk in chunks if chunk.metadata.get("chunk_kind") == "service_materials"]

    assert len(material_chunks) >= 2
    assert all(len(chunk.page_content) <= 1600 for chunk in material_chunks)
    assert all(chunk.metadata.get("chunk_fields") == ["办理材料", "精细化材料提醒"] for chunk in material_chunks)
    assert {chunk.metadata.get("chunk_part_index") for chunk in material_chunks} == set(range(1, len(material_chunks) + 1))


def test_changzhou_plugin_splits_overlong_markdown_table_qa_rows():
    source = "/path/to/gov-service-knowledge/03常州市常见问题/常州市高频应用知识.xlsx"
    long_answer = (
        "汽车置换更新申请说明。"
        + "申请人需确认车辆转让、报废、新车购置、补贴申领、资料审核等流程。" * 90
    )
    text = f"""Excel: 常州市高频应用知识.xlsx
Sheets: 高频应用

## Sheet: 高频应用

| 问题 | 相似问法 | 答案 |
| --- | --- | --- |
| 汽车置换更新 | 以旧换新、购车补贴 | {long_answer} |
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source, "file_type": "xlsx"}))
    chunks = _run_chunk(records)

    assert len(records) == 1
    assert records[0].metadata["gov_knowledge_type"] == "qa"
    assert len(chunks) >= 2
    assert all(chunk.metadata.get("chunk_kind") == "qa_pair" for chunk in chunks)
    assert all(len(chunk.page_content) <= 1600 for chunk in chunks)


def test_changzhou_plugin_governs_one_thing_guides_and_operations():
    guide_source = "/path/to/gov-service-knowledge/02高效办成一件事/一件事指南.txt"
    guide_text = """[残疾人服务“一件事”]
==##关键字：残疾证、残疾人补贴##==
涉及事项
残疾人证新办、困难残疾人生活补贴
办理须知
01残疾人证办理
申请人应为江苏省户籍。
申请材料
1.身份证
==##########==
[开办运输企业“一件事”]
涉及事项
道路货物运输经营许可
"""
    op_source = "/path/to/gov-service-knowledge/02高效办成一件事/一件事操作指引.txt"
    op_text = """残疾人服务“一件事”操作指引
一、系统入口
1.访问江苏政务服务网。
二、申报流程
1.点击在线办理。
--##########--
开办运输企业“一件事”操作指引
一、系统入口
1.进入旗舰店。
"""

    guide_records = _run_governance(Document(page_content=guide_text, metadata={"source": guide_source}))
    op_records = _run_governance(Document(page_content=op_text, metadata={"source": op_source}))

    assert [doc.metadata["gov_knowledge_type"] for doc in guide_records] == ["one_thing_guide", "one_thing_guide"]
    assert guide_records[0].metadata["case_title"] == "残疾人服务“一件事”"
    assert guide_records[0].metadata["keywords"] == ["残疾证", "残疾人补贴"]
    assert [doc.metadata["gov_knowledge_type"] for doc in op_records] == ["one_thing_operation", "one_thing_operation"]
    assert op_records[0].metadata["case_title"] == "残疾人服务“一件事”"


def test_changzhou_plugin_canonicalizes_one_thing_case_aliases():
    guide_source = "/path/to/gov-service-knowledge/02高效办成一件事/一件事指南.txt"
    guide_text = """[开办餐饮店“一件事”]
涉及事项
食品经营许可、营业执照
==##########==
[社会保障卡居民服务“一件事”]
涉及事项
社会保障卡申领、补领
==##########==
[企业注销登记“一件事”]
涉及事项
企业注销登记、税务注销
==##########==
[水电气网联合报装“一件事”]
涉及事项
供水报装、供电报装
"""
    op_source = "/path/to/gov-service-knowledge/02高效办成一件事/一件事操作指引.txt"
    op_text = """开餐饮店“一件事”操作指引
一、系统入口
1.进入高效办成一件事专区。
--##########--
社保卡服务“一件事”操作指引
一、系统入口
1.进入高效办成一件事专区。
--##########--
企业注销“一件事”操作指引
一、系统入口
1.进入高效办成一件事专区。
--##########--
水电气网联合报装“一件事”操作指引（建设单位）
一、系统入口
1.进入高效办成一件事专区。
"""

    guide_records = _run_governance(Document(page_content=guide_text, metadata={"source": guide_source}))
    op_records = _run_governance(Document(page_content=op_text, metadata={"source": op_source}))
    guide_by_key = {doc.metadata["case_key"]: doc.metadata["case_title"] for doc in guide_records}

    assert [doc.metadata["case_title"] for doc in op_records] == [
        "开办餐饮店“一件事”",
        "社会保障卡居民服务“一件事”",
        "企业注销登记“一件事”",
        "水电气网联合报装“一件事”",
    ]
    assert all(doc.metadata.get("case_title_raw") for doc in op_records)
    assert all(doc.metadata["case_key"] in guide_by_key for doc in op_records)


def test_changzhou_plugin_infers_one_thing_section_from_bare_uploaded_filenames():
    descriptor = describe_plugin_dir(PLUGIN_DIR, require_test_report=False)
    guide_text = """[残疾人服务“一件事”]
涉及事项
残疾人证新办、困难残疾人生活补贴
申请材料
1.居民身份证
"""
    op_text = """残疾人服务“一件事”操作指引
一、系统入口
1.访问江苏政务服务网常州综合服务旗舰店（https://cz.jszwfw.gov.cn/）。
二、申报流程
1.点击残疾人服务“一件事”模块。
"""

    guide_records = _run_governance(Document(page_content=guide_text, metadata={"source": "一件事指南.txt"}))
    op_records = _run_governance(Document(page_content=op_text, metadata={"source": "一件事操作指引.txt"}))
    chunks = _run_chunk([*guide_records, *op_records])

    assert [doc.metadata["knowledge_section"] for doc in [*guide_records, *op_records]] == [
        "02高效办成一件事",
        "02高效办成一件事",
    ]
    assert {chunk.metadata.get("chunk_kind") for chunk in chunks} >= {
        "one_thing_related_services",
        "one_thing_materials",
        "one_thing_operation_entry",
        "one_thing_operation_steps",
    }
    assert validate_documents_metadata(guide_records + op_records, metadata_schema=descriptor.metadata_schema, stage="governance")["ok"]
    assert validate_documents_metadata(chunks, metadata_schema=descriptor.metadata_schema, stage="chunk")["ok"]


def test_changzhou_plugin_chunks_one_thing_guides_by_business_sections():
    source = "/path/to/gov-service-knowledge/02高效办成一件事/一件事指南.txt"
    text = """[残疾人服务“一件事”]
==##关键字：残疾证、残疾人补贴##==
涉及事项
残疾人证新办、困难残疾人生活补贴、重度残疾人护理补贴
办理须知
01残疾人证办理
申请人应为江苏省户籍。
02困难残疾人生活补贴
申请人应为江苏省户籍的持证残疾人。
申请材料
1.通用材料：残疾人服务“一件事”申请表（系统自动生成）
2.专项材料
（1）残疾人证办理
①申请人本人居民身份证（电子证照库共享，免提交）
②申请人本人居民户口簿（电子证照库共享，免提交）
办理渠道
1.登录江苏政务服务网常州综合服务旗舰店**<https://cz.jszwfw.gov.cn/>**在线申请。
2.各级政务服务中心专窗提供咨询服务。
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)

    sections = {chunk.metadata.get("section_type"): chunk for chunk in chunks}
    assert {"related_services", "process", "materials", "channels"}.issubset(sections)
    assert sections["related_services"].metadata["related_services"] == [
        "残疾人证新办",
        "困难残疾人生活补贴",
        "重度残疾人护理补贴",
    ]
    assert sections["materials"].metadata["materials"] == [
        "通用材料：残疾人服务“一件事”申请表（系统自动生成）",
        "申请人本人居民身份证（电子证照库共享，免提交）",
        "申请人本人居民户口簿（电子证照库共享，免提交）",
    ]
    assert "检索锚点：" in sections["materials"].page_content
    assert "残疾人服务一件事" in sections["materials"].page_content
    assert "需要哪些材料" in sections["materials"].page_content
    assert "办理渠道" not in sections["materials"].page_content
    assert sections["channels"].metadata["urls"] == ["https://cz.jszwfw.gov.cn/"]
    assert "网上办理地址" in sections["channels"].page_content
    assert all(chunk.metadata.get("case_key") == "残疾人服务一件事" for chunk in chunks)
    assert all(chunk.metadata.get("chunk_kind") == f"one_thing_{chunk.metadata.get('section_type')}" for chunk in chunks)


def test_changzhou_plugin_chunks_one_thing_operations_by_entry_steps_and_urls():
    source = "/path/to/gov-service-knowledge/02高效办成一件事/一件事操作指引.txt"
    text = """残疾人服务“一件事”操作指引
一、系统入口
1.访问江苏政务服务网常州综合服务旗舰店（https://cz.jszwfw.gov.cn/）。
2.点击高效办成一件事服务模块。
二、申报流程
1.点击残疾人服务“一件事”模块。
2.登录后点击在线办理。
3.上传申报材料。
常州综合服务旗舰店办事微课堂跟着手册学操作：https://czqjd.jszwfw.gov.cn/course?id=4066
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)

    sections = {chunk.metadata.get("section_type"): chunk for chunk in chunks}
    assert {"operation_entry", "operation_steps", "operation_url"}.issubset(sections)
    assert sections["operation_entry"].metadata["urls"] == ["https://cz.jszwfw.gov.cn/"]
    assert sections["operation_url"].metadata["urls"] == ["https://czqjd.jszwfw.gov.cn/course?id=4066"]
    assert sections["operation_steps"].metadata["operation_steps"] == [
        "点击残疾人服务“一件事”模块。",
        "登录后点击在线办理。",
        "上传申报材料。",
    ]
    assert "检索锚点：" in sections["operation_steps"].page_content
    assert "残疾人服务一件事" in sections["operation_steps"].page_content
    assert "网上办理怎么操作" in sections["operation_steps"].page_content
    assert "申报步骤" in sections["operation_steps"].page_content
    assert sections["operation_steps"].metadata["retrieval_intents"] == ["申报流程", "申报步骤", "网上办理怎么操作"]
    assert sections["operation_steps"].metadata["step_no"] == 1


def test_changzhou_plugin_builds_structured_one_thing_kg_entities():
    guide_source = "/path/to/gov-service-knowledge/02高效办成一件事/一件事指南.txt"
    guide_text = """[残疾人服务“一件事”]
==##关键字：残疾证、残疾人补贴##==
涉及事项
残疾人证新办、困难残疾人生活补贴
申请材料
1.通用材料：残疾人服务“一件事”申请表（系统自动生成）
2.专项材料
①申请人本人居民身份证（电子证照库共享，免提交）
"""
    op_source = "/path/to/gov-service-knowledge/02高效办成一件事/一件事操作指引.txt"
    op_text = """残疾人服务“一件事”操作指引
二、申报流程
1.点击残疾人服务“一件事”模块。
2.上传申报材料。
常州综合服务旗舰店办事微课堂跟着手册学操作：https://czqjd.jszwfw.gov.cn/course?id=4066
"""

    chunks = _run_chunk(
        _run_governance(Document(page_content=guide_text, metadata={"source": guide_source}))
        + _run_governance(Document(page_content=op_text, metadata={"source": op_source}))
    )
    events = _run_kg(chunks)
    entity_pairs = {
        (entity["type"], entity["name"], entity.get("role"))
        for event in events
        for entity in event.get("entities", [])
    }

    assert ("OneThingCase", "残疾人服务“一件事”", "subject") in entity_pairs
    assert ("ServiceItem", "残疾人证新办", "related_service") in entity_pairs
    assert ("Material", "申请人本人居民身份证（电子证照库共享，免提交）", "material") in entity_pairs
    assert ("OperationStep", "点击残疾人服务“一件事”模块。", "operation_step") in entity_pairs
    assert ("Url", "https://czqjd.jszwfw.gov.cn/course?id=4066", "url") in entity_pairs


def test_changzhou_plugin_kg_labels_fit_storage_limits():
    source = "/path/to/gov-service-knowledge/04专题常见问答/超长问答.txt"
    long_question = "如何办理" + "超长政务事项" * 80
    long_answer = "请按政策材料要求办理。" + "补充说明" * 120
    long_url = "https://example.com/" + ("very-long-path/" * 60)
    text = f"""问题：[{long_question}]
答案：{long_answer}
来源部门：常州市测试部门
更多信息：{long_url}
"""

    chunks = _run_chunk(_run_governance(Document(page_content=text, metadata={"source": source})))
    events = _run_kg(chunks)

    assert events
    assert all(len(str(event.get("title") or "")) <= 255 for event in events)
    for event in events:
        for entity in event.get("entities", []):
            assert len(str(entity.get("name") or "")) <= 500
            assert len(str(entity.get("normalized_name") or "")) <= 500


def test_changzhou_plugin_governs_qa_records():
    source = "/path/to/gov-service-knowledge/06各区常见问题/经开区12345QA.txt"
    text = """问题：[住宅专项维修资金的交存标准是多少？]
==##相似问法：维修资金标准、维修基金多少钱##==
答案：配备电梯的，由业主按建筑面积每平方米120元标准交存。
来源部门：常州经济开发区建设局
==##########==
问题：[请问可以在哪里办理企业社会保险登记？]
答案：可以在常州经开区政务服务中心一楼大厅C区取号办理。
来源部门：常州经济开发区社会保障局
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)

    assert len(records) == 2
    assert records[0].metadata["knowledge_section"] == "06各区常见问题"
    assert records[0].metadata["gov_knowledge_type"] == "qa"
    assert records[0].metadata["district"] == "经开区"
    assert records[0].metadata["question"] == "住宅专项维修资金的交存标准是多少？"
    assert records[0].metadata["aliases"] == ["维修资金标准", "维修基金多少钱"]
    assert records[0].metadata["source_department"] == "常州经济开发区建设局"
    assert chunks[0].metadata["chunk_kind"] == "qa_pair"


def test_changzhou_plugin_infers_district_qa_section_from_bare_filename():
    source = "天宁区12345QA.txt"
    text = """问题：[请问《独生子女父母光荣证》补办是否收费]
答案：不收费
来源部门：常州市天宁区雕庄街道办事处
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)

    assert len(records) == 1
    assert records[0].metadata["knowledge_section"] == "06各区常见问题"
    assert records[0].metadata["district"] == "天宁区"
    assert records[0].metadata["source_topic"] == "天宁区12345QA"
    assert chunks[0].metadata["knowledge_section"] == "06各区常见问题"
    assert chunks[0].metadata["district"] == "天宁区"


def test_changzhou_plugin_clamps_long_qa_source_department_to_schema_limit():
    descriptor = describe_plugin_dir(PLUGIN_DIR, require_test_report=False)
    source = "/path/to/gov-service-knowledge/06各区常见问题/新北区12345QA.txt"
    long_department = "新北区教育局" + "招生入学咨询部门" * 80
    text = f"""问题：[义务教育学校招生怎么报名？]
答案：按当年招生入学政策和报名通知办理。
来源部门：{long_department}
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)

    assert len(records) == 1
    assert len(records[0].metadata["source_department"]) <= 300
    assert validate_documents_metadata(records, metadata_schema=descriptor.metadata_schema, stage="governance")["ok"]
    assert validate_documents_metadata(chunks, metadata_schema=descriptor.metadata_schema, stage="chunk")["ok"]


def test_changzhou_plugin_governs_qa_keywords_alias_variants_urls_and_topic():
    source = "/path/to/gov-service-knowledge/04专题常见问答/2026年常州市义务教育学校招生入学常见问题.txt"
    text = """问题：[小学入学需要哪些材料？]
==##关键字： 小学入学、报名材料、户口簿##==
==##相似问：上小学条件、幼升小报名材料##==
答案：凭户口簿、合法固定住所证件办理。点击查看相关通知：**<https://www.changzhou.gov.cn/gi_news/706177908756753>**
来源部门：常州市教育局
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)
    events = _run_kg(chunks)
    entity_pairs = {
        (entity["type"], entity["name"], entity.get("role"))
        for event in events
        for entity in event.get("entities", [])
    }

    assert len(records) == 1
    assert records[0].metadata["knowledge_section"] == "04专题常见问答"
    assert records[0].metadata["source_topic"] == "2026年常州市义务教育学校招生入学常见问题"
    assert records[0].metadata["question"] == "小学入学需要哪些材料？"
    assert records[0].metadata["keywords"] == ["小学入学", "报名材料", "户口簿"]
    assert records[0].metadata["aliases"] == ["上小学条件", "幼升小报名材料"]
    assert records[0].metadata["urls"] == ["https://www.changzhou.gov.cn/gi_news/706177908756753"]
    assert "==##关键字" not in records[0].metadata["answer"]
    assert "==##相似问" not in records[0].metadata["answer"]
    assert chunks[0].metadata["source_topic"] == records[0].metadata["source_topic"]
    assert ("Keyword", "小学入学", "keyword") in entity_pairs
    assert ("Url", "https://www.changzhou.gov.cn/gi_news/706177908756753", "url") in entity_pairs
    assert ("GovKnowledgeTopic", "2026年常州市义务教育学校招生入学常见问题", "source_topic") in entity_pairs


def test_changzhou_plugin_infers_topic_qa_section_from_bare_uploaded_filenames():
    source = "苏超购票常见问题.txt"
    text = """问题：[2026年苏超常规赛赛程安排]
==##相似问法：江苏省城市足球联赛2026赛季常规赛赛程##==
答案：江苏省城市足球联赛（简称“苏超”）2026赛季常规赛赛程正式发布。
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)

    assert len(records) == 1
    assert records[0].metadata["knowledge_section"] == "04专题常见问答"
    assert records[0].metadata["source_topic"] == "苏超购票常见问题"
    assert chunks[0].metadata["knowledge_section"] == "04专题常见问答"
    assert "主题：苏超购票常见问题" in chunks[0].page_content


def test_changzhou_plugin_governs_markdown_table_qa_rows_from_excel():
    source = "/path/to/gov-service-knowledge/03常州市常见问题/常州市高频应用知识.xlsx"
    text = """Excel: 常州市高频应用知识.xlsx
Sheets: 高频应用

## Sheet: 高频应用

| 问题 | 相似问法 | 答案 |
| --- | --- | --- |
| 汽车置换更新 | 以旧换新、购车补贴 | 汽车置换更新可在苏服办 APP 申请。申请流程：填报申请人信息-填报旧车销售信息-新车购置信息。 |
| 公积金业务 | 公积金提取、在哪办公积金业务？ | 可以从苏服办 APP 首页-公积金业务进入，也可访问 https://gjjyw.changzhou.gov.cn/wt/login |
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source, "file_type": "xlsx"}))
    chunks = _run_chunk(records)
    events = _run_kg(chunks)
    entity_pairs = {
        (entity["type"], entity["name"], entity.get("role"))
        for event in events
        for entity in event.get("entities", [])
    }

    assert len(records) == 2
    assert [record.metadata["gov_knowledge_type"] for record in records] == ["qa", "qa"]
    assert records[0].metadata["source_sheet"] == "高频应用"
    assert records[0].metadata["question"] == "汽车置换更新"
    assert records[0].metadata["aliases"] == ["以旧换新", "购车补贴"]
    assert records[1].metadata["urls"] == ["https://gjjyw.changzhou.gov.cn/wt/login"]
    assert [chunk.metadata["chunk_kind"] for chunk in chunks] == ["qa_pair", "qa_pair"]
    assert ("Question", "汽车置换更新", "subject") in entity_pairs
    assert ("Question", "购车补贴", "alias") in entity_pairs
    assert ("Url", "https://gjjyw.changzhou.gov.cn/wt/login", "url") in entity_pairs


def test_changzhou_plugin_infers_common_qa_section_from_bare_uploaded_filenames():
    source = "常州市本级12345QA.txt"
    text = """问题：[常州市市长质量奖如何申报？]
答案：每年上半年在常州市人民政府官网和市场监督管理局官网公布申报公告。
来源部门：常州市市场监督管理局
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))

    assert len(records) == 1
    assert records[0].metadata["knowledge_section"] == "03常州市常见问题"
    assert records[0].metadata["source_topic"] == "常州市本级12345QA"


def test_changzhou_plugin_governs_common_qa_structured_item_records():
    source = "/path/to/gov-service-knowledge/03常州市常见问题/核发居民身份证（首次申领、换领、补领、挂失、进度查询等知识）.txt"
    text = """事项名称：[核发居民身份证（换领）]
==##相似问法：身份证到期怎么换、线上换领身份证##==
受理条件：本省户籍人员凭居民身份证办理；省外户籍人员凭居民身份证和居住证明材料办理。
办理材料：居民身份证
办理流程：携带本人原居民身份证到就近的派出所或便民服务中心办理。
在线办理地址：通过“苏服办”APP网上办理（仅限本省户籍居民换补领）
注意事项：身份证到期可以提前3-6个月办理。
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)

    assert len(records) == 1
    assert records[0].metadata["gov_knowledge_type"] == "qa"
    assert records[0].metadata["question"] == "核发居民身份证（换领）"
    assert records[0].metadata["aliases"] == ["身份证到期怎么换", "线上换领身份证"]
    assert records[0].metadata["primary_alias"] == "身份证到期怎么换"
    assert "受理条件：本省户籍人员凭居民身份证办理" in records[0].metadata["answer"]
    assert "办理材料：居民身份证" in chunks[0].page_content
    assert chunks[0].metadata["chunk_kind"] == "qa_pair"


def test_changzhou_plugin_captures_unlabeled_common_qa_alias_markers():
    source = "/path/to/gov-service-knowledge/03常州市常见问题/常见问题优化补充.txt"
    text = """问题：[办理无房证明]
==##如何办理无房证明？常州无房证明怎么在线办理、如何申请无房证明？##==
答案：可以登录苏服办APP，在首页找到“不动产业务”，通过身份验证后办理。
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))

    assert len(records) == 1
    assert records[0].metadata["aliases"] == [
        "如何办理无房证明？常州无房证明怎么在线办理",
        "如何申请无房证明？",
    ]
    assert records[0].metadata["primary_alias"] == "如何办理无房证明？常州无房证明怎么在线办理"


def test_changzhou_plugin_repeats_qa_search_anchor_on_split_chunks():
    source = "/path/to/gov-service-knowledge/03常州市常见问题/常见问题优化补充.txt"
    answer = "第一段说明。" + "补充办理说明。" * 420
    text = f"""问题：[汽车置换补贴多久到账？]
==##相似问法：汽车补贴什么时候能发、置换补贴到账时间##==
答案：{answer}
"""

    chunks = _run_chunk(_run_governance(Document(page_content=text, metadata={"source": source})))

    assert len(chunks) > 1
    assert all("检索锚点：汽车置换补贴多久到账？" in chunk.page_content for chunk in chunks)
    assert all("汽车补贴什么时候能发" in chunk.page_content for chunk in chunks)


def test_changzhou_plugin_governs_excel_tables_with_title_row_before_header():
    source = "/path/to/gov-service-knowledge/03常州市常见问题/医保局近期问答.xlsx"
    text = """Excel: 医保局近期问答.xlsx
Sheets: 问答导出

## Sheet: 问答导出

| 医保局近期上传问答 |  |  |  |  |  |
| 序号 | 问答标题 | 问答答案 | 内容生效时间 | 内容失效时间 | 问答提供部门 |
| --- | --- | --- | --- | --- | --- |
| 1 | 职工医保参保人员的个人账户划入标准是多少？ | 35周岁以下本人缴费基数的2.9%。 | 2020-09-01 00:00:00 | 长期有效 | 常州市医疗保障局 |
| 2 | 《调整我市临时外出就医人员异地就医结算待遇的通知》执行时间是什么时候？ | 自2025年11月20日起执行。 | 2025-11-20 00:00:00 | 长期有效 | 常州市医疗保障局 |
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source, "file_type": "xlsx"}))
    chunks = _run_chunk(records)

    assert len(records) == 2
    assert records[0].metadata["gov_knowledge_type"] == "qa"
    assert records[0].metadata["question"] == "职工医保参保人员的个人账户划入标准是多少？"
    assert records[0].metadata["source_department"] == "常州市医疗保障局"
    assert records[0].metadata["source_sheet"] == "问答导出"
    assert records[0].metadata["valid_from"] == "2020-09-01 00:00:00"
    assert records[0].metadata["valid_to"] == "长期有效"
    assert all(chunk.metadata["chunk_kind"] == "qa_pair" for chunk in chunks)


def test_changzhou_plugin_governs_excel_parser_semicolon_rows():
    source = "/path/to/gov-service-knowledge/03常州市常见问题/全市政务服务中心（便民服务中心）位置及电话.xlsx"
    text = "[问题：常州市数据局位置]; ==##相似问法：常州市数据局地址、在哪里、在什么地方##==; 答案：常州市天宁区锦绣路2号 ——位置"

    records = _run_governance(Document(page_content=text, metadata={"source": source, "file_type": "xlsx"}))
    chunks = _run_chunk(records)

    assert len(records) == 1
    assert records[0].metadata["question"] == "常州市数据局位置"
    assert records[0].metadata["aliases"] == ["常州市数据局地址", "在哪里", "在什么地方"]
    assert records[0].metadata["answer"] == "常州市天宁区锦绣路2号"
    assert records[0].metadata["source_sheet"] == "位置"
    assert chunks[0].metadata["source_sheet"] == "位置"


def test_changzhou_plugin_preserves_department_table_business_metadata():
    source = "/path/to/gov-service-knowledge/05业务部门常见问题/公积金知识/线上业务.xlsx"
    text = """Excel: 线上业务.xlsx
Sheets: Sheet1

## Sheet: Sheet1

| 问题 | 答案 | 相似问法 | 关键词 | 适用区域 | 办事链接 | 来源部门 |
| --- | --- | --- | --- | --- | --- | --- |
| 线上业务渠道 | 可通过常州住房公积金微信公众号、苏服办 APP、江苏政务服务网办理。 | 公积金线上入口、网上办理公积金 | 个人业务 | 常州全市 | https://gjj.changzhou.gov.cn/ | 公积金中心 |
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source, "file_type": "xlsx"}))
    events = _run_kg(_run_chunk(records))
    entity_pairs = {
        (entity["type"], entity["name"], entity.get("role"))
        for event in events
        for entity in event.get("entities", [])
    }

    assert len(records) == 1
    assert records[0].metadata["keywords"] == ["个人业务"]
    assert records[0].metadata["applicable_area"] == "常州全市"
    assert records[0].metadata["service_url"] == "https://gjj.changzhou.gov.cn/"
    assert records[0].metadata["urls"] == ["https://gjj.changzhou.gov.cn/"]
    assert records[0].metadata["source_department"] == "公积金中心"
    assert ("Keyword", "个人业务", "keyword") in entity_pairs
    assert ("Region", "常州全市", "applicable_area") in entity_pairs
    assert ("Url", "https://gjj.changzhou.gov.cn/", "url") in entity_pairs


def test_changzhou_plugin_infers_department_section_from_relative_upload_paths():
    source = "公积金知识/线上业务.xlsx"
    text = """Excel: 线上业务.xlsx
Sheets: Sheet1

## Sheet: Sheet1

| 问题 | 答案 | 相似问法 | 关键词 | 适用区域 | 办事链接 | 来源部门 |
| --- | --- | --- | --- | --- | --- | --- |
| 线上业务渠道 | 可通过常州住房公积金微信公众号办理。 | 公积金线上入口 | 个人业务 | 常州全市 | https://gjj.changzhou.gov.cn/ | 公积金中心 |
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source, "file_type": "xlsx"}))
    chunks = _run_chunk(records)

    assert len(records) == 1
    assert records[0].metadata["knowledge_section"] == "05业务部门常见问题"
    assert records[0].metadata["department_domain"] == "公积金知识"
    assert records[0].metadata["source_topic"] == "线上业务"
    assert chunks[0].metadata["knowledge_section"] == "05业务部门常见问题"


def test_changzhou_plugin_infers_emergency_department_from_bare_filename():
    source = "应急局日常问题汇总.docx"
    text = """用户管理
企业员工密码输入错误5次，无法再输入密码。
答：企业可通过重置密码，刷新输入限制次数。
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source, "file_type": "docx"}))

    assert len(records) == 1
    assert records[0].metadata["knowledge_section"] == "05业务部门常见问题"
    assert records[0].metadata["department_domain"] == "应急局"
    assert records[0].metadata["source_topic"] == "应急局日常问题汇总"
    assert records[0].metadata["category_path"] == ["应急局日常问题汇总", "用户管理"]


def test_changzhou_plugin_cleans_numbered_emergency_loose_qa():
    source = "应急局日常问题汇总.docx"
    text = """粉尘企业在粉尘专项中，无清扫任务
1. **“应清尽清”显示不符合**
答：查看集中除尘器是否在室内，在室内不符合。
2. **粉尘清扫记录看不到**
答：进入粉尘专项模块查看清扫记录。
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source, "file_type": "docx"}))
    chunks = _run_chunk(records)

    assert len(records) == 2
    assert records[0].metadata["question"] == "“应清尽清”显示不符合"
    assert records[0].metadata["category_path"] == ["应急局日常问题汇总", "粉尘企业在粉尘专项中，无清扫任务"]
    assert chunks[0].metadata["qa_anchor"].startswith("检索锚点：“应清尽清”显示不符合")
    assert "1. **" not in chunks[0].page_content


def test_changzhou_plugin_infers_department_regulation_from_bare_filename():
    source = "10.自然资源部关于取消一批证明事项的公告（自然资源部公告2019年第23号）.docx"
    text = """自然资源部关于取消一批证明事项的公告
第一条 取消申请材料中的部分证明事项。
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source, "file_type": "docx"}))
    chunks = _run_chunk(records)

    assert len(records) == 1
    assert records[0].metadata["knowledge_section"] == "05业务部门常见问题"
    assert records[0].metadata["department_domain"] == "不动产知识库"
    assert records[0].metadata["gov_knowledge_type"] == "regulation_text"
    assert chunks[0].metadata["knowledge_section"] == "05业务部门常见问题"


def test_changzhou_plugin_preserves_real_estate_category_path_from_table():
    source = "/path/to/gov-service-knowledge/05业务部门常见问题/不动产知识库/不动产常见问答.xlsx"
    text = """Excel: 不动产常见问答.xlsx
Sheets: 可导入版本

## Sheet: 可导入版本

| 类目路径（多级类目用/分隔） | 问题 | 相似问法 | 答案 |
| --- | --- | --- | --- |
| 常州/转移登记 | 房地产买卖办理需要多久？ | 房产过户多久、买卖房子多久办完 | 办理时限：自受理登记后3个工作日。 |
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source, "file_type": "xlsx"}))
    events = _run_kg(_run_chunk(records))
    entity_pairs = {
        (entity["type"], entity["name"], entity.get("role"))
        for event in events
        for entity in event.get("entities", [])
    }

    assert len(records) == 1
    assert records[0].metadata["category_path"] == ["常州", "转移登记"]
    assert records[0].metadata["category_leaf"] == "转移登记"
    assert ("BusinessCategory", "转移登记", "category") in entity_pairs


def test_changzhou_plugin_governs_loose_answer_marker_docx_faq():
    source = "/path/to/gov-service-knowledge/05业务部门常见问题/应急局日常问题汇总.docx"
    text = """【常州应急】常见问题解答
用户管理
企业在应急系统注册时，系统提示“该企业统一社会信用代码已被注册”。
答：由政府人员在数据治理 -- 企业档案中查看该企业是否存在。
在企业档案 -- 员工信息中查看企业是否存在员工信息。
企业员工密码输入错误5次，无法再输入密码。
答：企业可通过重置密码，刷新输入限制次数。
标签管理
企业标签管理（企业状态、行政区域变更）
答：由政府人员在数据治理 -- 标签管理中进行变更。
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source, "file_type": "docx"}))
    chunks = _run_chunk(records)

    assert len(records) == 3
    assert records[0].metadata["gov_knowledge_type"] == "qa"
    assert records[0].metadata["source_topic"] == "应急局日常问题汇总"
    assert records[0].metadata["category_path"] == ["应急局日常问题汇总", "用户管理"]
    assert records[0].metadata["category_leaf"] == "用户管理"
    assert records[0].metadata["question"] == "企业在应急系统注册时，系统提示“该企业统一社会信用代码已被注册”。"
    assert "员工信息" in records[0].metadata["answer"]
    assert records[2].metadata["category_leaf"] == "标签管理"
    assert all(chunk.metadata["chunk_kind"] == "qa_pair" for chunk in chunks)


def test_changzhou_golden_rules_use_record_level_expected_metadata():
    golden_rules = json.loads((PLUGIN_DIR / "golden_rules.json").read_text(encoding="utf-8"))

    assert golden_rules["expected_metadata"] == [
        "source_record_id",
        "gov_knowledge_type",
        "knowledge_section",
    ]


def test_changzhou_golden_rules_cover_one_thing_section_chunks():
    golden_rules = json.loads((PLUGIN_DIR / "golden_rules.json").read_text(encoding="utf-8"))
    templates = golden_rules["query_templates"]

    assert {
        "one_thing_related_services",
        "one_thing_process",
        "one_thing_materials",
        "one_thing_channels",
        "one_thing_conditions",
        "one_thing_operation_entry",
        "one_thing_operation_steps",
        "one_thing_operation_url",
        "one_thing_operation_notes",
    }.issubset(templates)


def test_changzhou_plugin_sample_includes_one_thing_operation_branch():
    raw_items = json.loads((PLUGIN_DIR / "sample.json").read_text(encoding="utf-8"))
    sample_docs = [
        Document(page_content=item["page_content"], metadata=dict(item.get("metadata") or {}))
        for item in raw_items
    ]
    records: list[Document] = []
    for doc in sample_docs:
        records.extend(_run_governance(doc))
    chunks = _run_chunk(records)

    assert any(record.metadata.get("gov_knowledge_type") == "one_thing_operation" for record in records)
    assert any(chunk.metadata.get("chunk_kind") == "one_thing_operation_steps" for chunk in chunks)
    assert any(chunk.metadata.get("chunk_kind") == "one_thing_operation_url" for chunk in chunks)


def test_changzhou_plugin_marks_long_regulation_text_as_section_chunks():
    source = "/path/to/gov-service-knowledge/05业务部门常见问题/不动产知识库/不动产法规汇编/法规汇编/二、行政法规/二、行政法规.txt"
    text = """中华人民共和国不动产登记暂行条例
第一章 总则
第一条 为整合不动产登记职责，规范登记行为，制定本条例。
第二条 本条例所称不动产登记，是指登记机构依法将不动产权利归属和其他法定事项记载于不动产登记簿的行为。
==##########==
不动产登记暂行条例实施细则
第一章 总则
第一条 为规范不动产登记行为，细化登记程序，制定本实施细则。
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))
    chunks = _run_chunk(records)

    assert len(records) == 2
    assert records[0].metadata["gov_knowledge_type"] == "regulation_text"
    assert records[0].metadata["knowledge_section"] == "05业务部门常见问题"
    assert records[0].metadata["department_domain"] == "不动产知识库"
    assert chunks[0].metadata["chunk_kind"] == "regulation_section"


def test_changzhou_plugin_preserves_multiline_regulation_titles():
    source = "/path/to/gov-service-knowledge/05业务部门常见问题/不动产知识库/不动产法规汇编/法规汇编/三、司法解释/三、司法解释.docx"
    text = """最高人民法院
关于破产企业国有划拨土地使用权应否列入
破产财产等问题的批复
（2002年10月11日最高人民法院审判委员会通过）
湖北省高级人民法院：
你院请示收悉。经研究，答复如下：
一、破产企业以划拨方式取得的国有土地使用权不属于破产财产。
"""

    records = _run_governance(Document(page_content=text, metadata={"source": source}))

    assert records[0].metadata["title"] == "最高人民法院关于破产企业国有划拨土地使用权应否列入破产财产等问题的批复"


def test_changzhou_plugin_disables_builtin_governance_after_plugin_governance():
    descriptor = describe_plugin_dir(PLUGIN_DIR, require_test_report=False)

    assert descriptor.suggested_pipeline_patch["governance_enabled"] is False
    assert descriptor.suggested_pipeline_patch["persist_parsed_content"] is True
    assert descriptor.refs["governance"]
    assert descriptor.refs["chunk"]


def test_changzhou_plugin_is_executable_after_local_report():
    descriptor = describe_plugin_dir(PLUGIN_DIR)

    assert descriptor.id == "changzhou-gov-service-knowledge"
    assert descriptor.published is True
    assert descriptor.executable is True
    assert descriptor.refs["governance"] == "plugin:changzhou-gov-service-knowledge@1.0.0:governance"
    assert descriptor.refs["chunk"] == "plugin:changzhou-gov-service-knowledge@1.0.0:chunk"
    assert descriptor.refs["kg"] == "plugin:changzhou-gov-service-knowledge@1.0.0:kg"
