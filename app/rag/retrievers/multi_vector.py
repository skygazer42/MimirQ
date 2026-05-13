"""
Multi-Vector Retriever for RAG systems.

Supports multiple vector representations per document:
- Raw document chunks
- Document summaries
- Hypothetical questions (HyDE)
- Parent document references

This enables decoupling retrieval representations from synthesis content.

Usage:
    from app.rag.retrievers.multi_vector import MultiVectorRetriever

    retriever = MultiVectorRetriever(
        vectorstore=my_vectorstore,
        docstore=my_docstore,
    )

    # Add documents with multiple representations
    retriever.add_documents(docs, summaries=doc_summaries)

    # Retrieve using summary vectors, return original docs
    results = retriever.retrieve(query)
"""


import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from app.rag.core.logging import get_logger

logger = get_logger("rag.retrievers.multi_vector")


class RepresentationType(str, Enum):
    """Types of document representations."""
    RAW = "raw"  # Original document content
    SUMMARY = "summary"  # Document summary
    HYPOTHETICAL_QUESTION = "hypothetical_question"  # Generated questions (HyDE)
    PARENT = "parent"  # Parent document reference
    SMALLER_CHUNK = "smaller_chunk"  # Smaller chunks for retrieval


@dataclass
class DocumentRepresentation:
    """A single representation of a document."""
    id: str
    doc_id: str  # ID of the original document
    type: RepresentationType
    content: str
    vector: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseDocStore(ABC):
    """Abstract base class for document storage."""

    @abstractmethod
    def add(self, docs: dict[str, Document]) -> None:
        """Add documents to the store."""
        pass

    @abstractmethod
    def get(self, doc_ids: list[str]) -> dict[str, Document]:
        """Get documents by IDs."""
        pass

    @abstractmethod
    def delete(self, doc_ids: list[str]) -> None:
        """Delete documents by IDs."""
        pass

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[Document]:
        """Search documents (optional, for hybrid search)."""
        pass


class InMemoryDocStore(BaseDocStore):
    """In-memory document store."""

    def __init__(self):
        self._docs: dict[str, Document] = {}

    def add(self, docs: dict[str, Document]) -> None:
        self._docs.update(docs)

    def get(self, doc_ids: list[str]) -> dict[str, Document]:
        return {doc_id: self._docs[doc_id] for doc_id in doc_ids if doc_id in self._docs}

    def delete(self, doc_ids: list[str]) -> None:
        for doc_id in doc_ids:
            self._docs.pop(doc_id, None)

    def search(self, query: str, limit: int = 10) -> list[Document]:
        # Simple keyword search fallback
        query_lower = query.lower()
        results = []
        for doc in self._docs.values():
            if query_lower in doc.page_content.lower():
                results.append(doc)
                if len(results) >= limit:
                    break
        return results


class MultiVectorRetriever(BaseRetriever):
    """
    Multi-Vector Retriever that stores multiple representations per document.

    Key concept: Decouple the vectors used for retrieval from the documents
    returned for synthesis. This allows:

    1. **Summary-based retrieval**: Index summaries, return full documents
    2. **HyDE**: Index hypothetical questions, return actual content
    3. **Parent-child**: Index small chunks, return larger parent chunks

    Attributes:
        vectorstore: Vector store for embeddings
        docstore: Document store for original documents
        id_key: Metadata key linking representations to documents
        search_type: Type of search ("similarity", "mmr")
        search_kwargs: Additional search parameters
    """

    vectorstore: Any = None
    docstore: BaseDocStore | None = None
    id_key: str = "doc_id"
    search_type: str = "similarity"
    search_kwargs: dict[str, Any] = {}

    # Private attributes
    _embedding_func: Callable | None = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(
        self,
        vectorstore: Any = None,
        docstore: BaseDocStore | None = None,
        embedding_func: Callable | None = None,
        id_key: str = "doc_id",
        search_type: str = "similarity",
        search_kwargs: dict[str, Any] | None = None,
        **kwargs,
    ):
        """
        Initialize the multi-vector retriever.

        Args:
            vectorstore: Vector store instance (from langchain or app.storage.vector)
            docstore: Document store for full documents
            embedding_func: Function to generate embeddings
            id_key: Metadata key for document IDs
            search_type: Search type ("similarity" or "mmr")
            search_kwargs: Additional search parameters
        """
        super().__init__(**kwargs)
        self.vectorstore = vectorstore
        self.docstore = docstore or InMemoryDocStore()
        self._embedding_func = embedding_func
        self.id_key = id_key
        self.search_type = search_type
        self.search_kwargs = search_kwargs or {}

    def add_documents(
        self,
        documents: list[Document],
        *,
        representations: list[list[str]] | None = None,
        representation_type: RepresentationType = RepresentationType.RAW,
        ids: list[str] | None = None,
        add_to_docstore: bool = True,
    ) -> list[str]:
        """
        Add documents with optional alternative representations.

        Args:
            documents: Original documents to store
            representations: Alternative text representations for each document
                (e.g., summaries, questions). If None, uses document content.
            representation_type: Type of the representations
            ids: Optional document IDs (generated if not provided)
            add_to_docstore: Whether to add documents to docstore

        Returns:
            List of document IDs
        """
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in documents]

        if len(ids) != len(documents):
            raise ValueError("Number of IDs must match number of documents")

        # Add to docstore
        if add_to_docstore:
            doc_dict = dict(zip(ids, documents, strict=False))
            self.docstore.add(doc_dict)

        # Prepare vectors for indexing
        if representations is None:
            # Use document content directly
            texts_to_embed = [doc.page_content for doc in documents]
            metadatas = [
                {**doc.metadata, self.id_key: doc_id, "representation_type": representation_type.value}
                for doc_id, doc in zip(ids, documents, strict=False)
            ]
        else:
            # Use provided representations
            texts_to_embed = []
            metadatas = []
            for doc_id, doc, reps in zip(ids, documents, representations, strict=False):
                for rep in reps:
                    texts_to_embed.append(rep)
                    metadatas.append({
                        **doc.metadata,
                        self.id_key: doc_id,
                        "representation_type": representation_type.value,
                    })

        # Add to vectorstore
        if self.vectorstore is not None and texts_to_embed:
            self.vectorstore.add_texts(texts_to_embed, metadatas=metadatas)

        logger.info(
            "Added %d documents with %d representations (type=%s)",
            len(documents), len(texts_to_embed), representation_type.value
        )

        return ids

    def add_summaries(
        self,
        documents: list[Document],
        summaries: list[str],
        ids: list[str] | None = None,
    ) -> list[str]:
        """
        Add documents with summary representations.

        Args:
            documents: Original documents
            summaries: Summaries for each document
            ids: Optional document IDs

        Returns:
            List of document IDs
        """
        if len(summaries) != len(documents):
            raise ValueError("Number of summaries must match number of documents")

        return self.add_documents(
            documents,
            representations=[[s] for s in summaries],
            representation_type=RepresentationType.SUMMARY,
            ids=ids,
        )

    def add_hypothetical_questions(
        self,
        documents: list[Document],
        questions: list[list[str]],
        ids: list[str] | None = None,
    ) -> list[str]:
        """
        Add documents with hypothetical question representations (HyDE).

        Args:
            documents: Original documents
            questions: Lists of hypothetical questions for each document
            ids: Optional document IDs

        Returns:
            List of document IDs
        """
        if len(questions) != len(documents):
            raise ValueError("Number of question lists must match number of documents")

        return self.add_documents(
            documents,
            representations=questions,
            representation_type=RepresentationType.HYPOTHETICAL_QUESTION,
            ids=ids,
        )

    def add_parent_child(
        self,
        parent_documents: list[Document],
        child_chunks: list[list[Document]],
        parent_ids: list[str] | None = None,
    ) -> list[str]:
        """
        Add parent documents with smaller child chunks for retrieval.

        Child chunks are indexed for retrieval, but parent documents
        are returned.

        Args:
            parent_documents: Parent (larger) documents
            child_chunks: Lists of child chunks for each parent
            parent_ids: Optional parent document IDs

        Returns:
            List of parent document IDs
        """
        if parent_ids is None:
            parent_ids = [str(uuid.uuid4()) for _ in parent_documents]

        if len(parent_ids) != len(parent_documents):
            raise ValueError("Number of IDs must match number of parent documents")

        # Add parents to docstore
        parent_dict = dict(zip(parent_ids, parent_documents, strict=False))
        self.docstore.add(parent_dict)

        # Add child chunks to vectorstore with parent reference
        texts_to_embed = []
        metadatas = []

        for parent_id, _parent_doc, children in zip(parent_ids, parent_documents, child_chunks, strict=False):
            for child in children:
                texts_to_embed.append(child.page_content)
                metadatas.append({
                    **child.metadata,
                    self.id_key: parent_id,
                    "representation_type": RepresentationType.SMALLER_CHUNK.value,
                    "parent_id": parent_id,
                })

        if self.vectorstore is not None and texts_to_embed:
            self.vectorstore.add_texts(texts_to_embed, metadatas=metadatas)

        logger.info(
            "Added %d parent documents with %d child chunks",
            len(parent_documents), len(texts_to_embed)
        )

        return parent_ids

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        """
        Retrieve relevant documents.

        Searches vectorstore for representations, then returns
        corresponding original documents from docstore.
        """
        if self.vectorstore is None:
            logger.warning("No vectorstore configured, falling back to docstore search")
            return self.docstore.search(query, limit=self.search_kwargs.get("k", 4))

        # Search vectorstore
        if self.search_type == "mmr":
            results = self.vectorstore.max_marginal_relevance_search(
                query, **self.search_kwargs
            )
        else:
            results = self.vectorstore.similarity_search(
                query, **self.search_kwargs
            )

        # Extract document IDs
        doc_ids = []
        seen = set()
        for doc in results:
            doc_id = doc.metadata.get(self.id_key)
            if doc_id and doc_id not in seen:
                doc_ids.append(doc_id)
                seen.add(doc_id)

        # Fetch original documents
        if not doc_ids:
            return []

        docs_dict = self.docstore.get(doc_ids)

        # Preserve order and add retrieval metadata
        output = []
        for i, doc_id in enumerate(doc_ids):
            if doc_id in docs_dict:
                doc = docs_dict[doc_id]
                # Add retrieval info to metadata
                doc.metadata["retrieval_rank"] = i
                doc.metadata["retrieval_doc_id"] = doc_id
                output.append(doc)

        return output

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager,
    ) -> list[Document]:
        """Async version of _get_relevant_documents."""
        # For now, just call sync version
        return self._get_relevant_documents(
            query,
            run_manager=CallbackManagerForRetrieverRun.get_noop_manager()
        )


def create_summary_retriever(
    vectorstore: Any,
    llm: Any,
    documents: list[Document],
    **kwargs,
) -> MultiVectorRetriever:
    """
    Create a multi-vector retriever that indexes summaries.

    Args:
        vectorstore: Vector store for embeddings
        llm: Language model for generating summaries
        documents: Documents to index
        **kwargs: Additional retriever arguments

    Returns:
        Configured MultiVectorRetriever
    """
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    # Generate summaries
    prompt = ChatPromptTemplate.from_template(
        "Summarize the following document in 2-3 sentences:\n\n{doc}"
    )
    chain = prompt | llm | StrOutputParser()

    summaries = []
    for doc in documents:
        try:
            summary = chain.invoke({"doc": doc.page_content[:4000]})
            summaries.append(summary)
        except Exception as e:
            logger.warning("Failed to generate summary: %s", e)
            summaries.append(doc.page_content[:500])  # Fallback to truncated content

    # Create retriever
    retriever = MultiVectorRetriever(vectorstore=vectorstore, **kwargs)
    retriever.add_summaries(documents, summaries)

    return retriever


def create_hypothetical_question_retriever(
    vectorstore: Any,
    llm: Any,
    documents: list[Document],
    questions_per_doc: int = 3,
    **kwargs,
) -> MultiVectorRetriever:
    """
    Create a multi-vector retriever using HyDE (Hypothetical Document Embeddings).

    Generates hypothetical questions for each document and indexes those.

    Args:
        vectorstore: Vector store for embeddings
        llm: Language model for generating questions
        documents: Documents to index
        questions_per_doc: Number of questions to generate per document
        **kwargs: Additional retriever arguments

    Returns:
        Configured MultiVectorRetriever
    """
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    # Generate hypothetical questions
    prompt = ChatPromptTemplate.from_template(
        f"""Generate {questions_per_doc} questions that this document could answer.
Return only the questions, one per line.

Document:
{{doc}}

Questions:"""
    )
    chain = prompt | llm | StrOutputParser()

    all_questions = []
    for doc in documents:
        try:
            response = chain.invoke({"doc": doc.page_content[:4000]})
            questions = [q.strip() for q in response.strip().split("\n") if q.strip()]
            all_questions.append(questions[:questions_per_doc])
        except Exception as e:
            logger.warning("Failed to generate questions: %s", e)
            all_questions.append([doc.page_content[:200]])  # Fallback

    # Create retriever
    retriever = MultiVectorRetriever(vectorstore=vectorstore, **kwargs)
    retriever.add_hypothetical_questions(documents, all_questions)

    return retriever


def create_parent_child_retriever(
    vectorstore: Any,
    parent_documents: list[Document],
    child_splitter: Any,
    **kwargs,
) -> MultiVectorRetriever:
    """
    Create a parent-child multi-vector retriever.

    Indexes smaller chunks for retrieval but returns parent documents.

    Args:
        vectorstore: Vector store for embeddings
        parent_documents: Parent (larger) documents
        child_splitter: Text splitter for creating child chunks
        **kwargs: Additional retriever arguments

    Returns:
        Configured MultiVectorRetriever
    """
    # Split parents into children
    all_children = []
    for parent in parent_documents:
        children = child_splitter.split_documents([parent])
        all_children.append(children)

    # Create retriever
    retriever = MultiVectorRetriever(vectorstore=vectorstore, **kwargs)
    retriever.add_parent_child(parent_documents, all_children)

    return retriever


# Export for easier imports
__all__ = [
    "MultiVectorRetriever",
    "RepresentationType",
    "DocumentRepresentation",
    "BaseDocStore",
    "InMemoryDocStore",
    "create_summary_retriever",
    "create_hypothetical_question_retriever",
    "create_parent_child_retriever",
]
