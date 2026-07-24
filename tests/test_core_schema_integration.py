import uuid

from app.models.chat import Conversation, Message
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document, DocumentChunk
from app.models.tenant import Tenant, TenantMember


def test_migrated_schema_supports_core_knowledge_flow(pg_session) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    message_id = uuid.uuid4()

    pg_session.add_all(
        [
            Tenant(id=tenant_id, name=f"integration-{tenant_id}"),
            TenantMember(tenant_id=tenant_id, user_id="integration-user", is_current=True),
            Dataset(
                id=dataset_id,
                tenant_id=tenant_id,
                name="integration-dataset",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="integration-user",
                dataset_metadata={},
            ),
            Document(
                id=document_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                filename="integration.txt",
                file_type="txt",
                file_size=11,
                file_path="uploads/integration.txt",
                status="completed",
                owner_id="integration-user",
                doc_metadata={},
            ),
            DocumentChunk(
                id=chunk_id,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=0,
                content="hello world",
                doc_metadata={},
            ),
            Conversation(
                id=conversation_id,
                tenant_id=tenant_id,
                owner_account_id="integration-user",
                dataset_id=dataset_id,
                document_ids=[document_id],
                title="Integration",
            ),
            Message(
                id=message_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role="user",
                content="hello",
            ),
        ]
    )
    pg_session.commit()
    pg_session.expunge_all()

    assert pg_session.get(Tenant, tenant_id).name.startswith("integration-")
    assert pg_session.get(Dataset, dataset_id).tenant_id == tenant_id
    assert pg_session.get(Document, document_id).dataset_id == dataset_id
    assert pg_session.get(DocumentChunk, chunk_id).document_id == document_id
    assert pg_session.get(Conversation, conversation_id).document_ids == [document_id]
    assert pg_session.get(Message, message_id).conversation_id == conversation_id
