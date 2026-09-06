"""RAGBackend — abstract interface for knowledge retrieval.

All RAG implementations (RAGFlow, local, custom) must subclass this.
"""
from abc import ABC, abstractmethod


class RAGBackend(ABC):
    """Abstract knowledge retrieval backend."""

    @abstractmethod
    def search(self, question: str, dataset_ids: list = None, top_k: int = 5) -> list:
        """Search knowledge bases for relevant information.
        Returns list of {content, dataset_id, dataset_name, document_name, similarity}
        """

    @abstractmethod
    def list_datasets(self) -> list:
        """List available knowledge bases.
        Returns list of {id, name, chunk_count, description}
        """

    def create_dataset(self, name: str, description: str = "") -> dict:
        """Optional: create a new knowledge base."""
        raise NotImplementedError

    def upload_document(self, dataset_id: str, file_path: str) -> dict:
        """Optional: upload a document to a knowledge base."""
        raise NotImplementedError

    def name(self) -> str:
        """Backend identifier."""
        return self.__class__.__name__

    def get_tool_definitions(self) -> list:
        """Return LLM function-calling tool definitions.

        Override to customize what tools this backend exposes.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "rag_search",
                    "description": "Search knowledge bases for design reference data. "
                                  "Use for material specs, tolerances, fastener data, "
                                  "or any factual information needed during design.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "Search query"},
                            "top_k": {"type": "integer", "description": "Number of results", "default": 5},
                        },
                        "required": ["question"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "rag_list_datasets",
                    "description": "List all available knowledge bases.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]
