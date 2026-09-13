import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.documents import Document

from backend.agent.rag_graph import rag_graph
from backend.agent.rag_planner import create_retrieval_plan
from backend.agent.rag_retrieval import bm25_search, vector_search
from backend.schemas.rag import RagFilters, RagQuery, RetrievalTask, RetrievedChunk


def make_chunk(
    *,
    document_id: str,
    chunk_index: int,
    content: str,
    source: str,
    score: float = 0.8,
    retrieval_source: str = "test",
    task_id: str | None = None,
) -> RetrievedChunk:
    metadata = {
        "document_id": document_id,
        "chunk_index": chunk_index,
        "num": chunk_index,
        "source": source,
        "category": "user_upload",
    }
    if task_id:
        metadata["_retrieval_task_id"] = task_id
    return RetrievedChunk(
        chunk_id=f"{document_id}:{chunk_index}",
        document_id=document_id,
        content=content,
        metadata=metadata,
        retrieval_source=retrieval_source,
        retrieval_rank=1,
        retrieval_score=score,
    )


class RagPlannerTests(unittest.TestCase):
    def test_auto_with_subqueries_uses_complex(self):
        plan, warnings = create_retrieval_plan(
            RagQuery(
                query="比较 A 和 B",
                sub_queries=["A 是什么", "B 是什么"],
                keywords=["A", "B"],
            )
        )

        self.assertEqual(plan.mode, "complex")
        self.assertFalse(warnings)
        self.assertEqual(
            {task.task_id for task in plan.tasks},
            {
                "main:vector",
                "main:bm25",
                "sub:0:vector",
                "sub:0:bm25",
                "sub:1:vector",
                "sub:1:bm25",
            },
        )


class RagGraphTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.vector_results = [
            make_chunk(
                document_id="doc-1",
                chunk_index=0,
                content="RAG 通过检索外部知识增强回答。",
                source="rag.md",
                score=0.9,
                retrieval_source="vector",
                task_id="main:vector",
            )
        ]
        self.bm25_results = [
            make_chunk(
                document_id="doc-1",
                chunk_index=0,
                content="RAG 通过检索外部知识增强回答。",
                source="rag.md",
                score=1.2,
                retrieval_source="bm25",
                task_id="main:bm25",
            ),
            make_chunk(
                document_id="doc-2",
                chunk_index=2,
                content="重排用于调整候选证据的顺序。",
                source="rerank.md",
                score=0.7,
                retrieval_source="bm25",
                task_id="main:bm25",
            ),
        ]

    async def test_pipeline_returns_success_result(self):
        async def parent_window(*, user_id, document_id, center_index, window):
            return [
                make_chunk(
                    document_id=document_id,
                    chunk_index=index,
                    content=f"{document_id} 的第 {index} 块证据。",
                    source=f"{document_id}.md",
                )
                for index in range(max(0, center_index - window), center_index + window + 1)
            ]

        request = RagQuery(
            query="RAG 如何工作？",
            keywords=["RAG"],
            top_k=3,
            include_diagnostics=True,
        )
        with (
            patch(
                "backend.agent.rag_graph.vector_search",
                new=AsyncMock(return_value=self.vector_results),
            ),
            patch(
                "backend.agent.rag_graph.bm25_search",
                new=AsyncMock(return_value=self.bm25_results),
            ),
            patch(
                "backend.agent.rag_graph.fetch_parent_window",
                new=AsyncMock(side_effect=parent_window),
            ),
        ):
            state = await rag_graph.ainvoke({"request": request, "user_id": 1})

        result = state["result"]
        self.assertEqual(result.status, "success")
        self.assertTrue(result.context)
        self.assertTrue(result.citations)
        self.assertIsNotNone(result.diagnostics)
        doc1_evidence = next(
            evidence
            for evidence in state["expanded"]
            if evidence.document_id == "doc-1"
        )
        self.assertEqual(len(doc1_evidence.metadata["_retrieval_hits"]), 2)

    async def test_pipeline_returns_no_result(self):
        request = RagQuery(query="不存在的内容")
        with (
            patch(
                "backend.agent.rag_graph.vector_search",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "backend.agent.rag_graph.bm25_search",
                new=AsyncMock(return_value=[]),
            ),
        ):
            state = await rag_graph.ainvoke({"request": request, "user_id": 1})

        result = state["result"]
        self.assertEqual(result.status, "no_result")
        self.assertEqual(result.context, "")
        self.assertEqual(result.citations, [])

    async def test_pipeline_returns_failed_when_all_channels_fail(self):
        request = RagQuery(query="测试失败")
        with (
            patch(
                "backend.agent.rag_graph.vector_search",
                new=AsyncMock(side_effect=ConnectionError("vector unavailable")),
            ),
            patch(
                "backend.agent.rag_graph.bm25_search",
                new=AsyncMock(side_effect=ConnectionError("bm25 unavailable")),
            ),
        ):
            state = await rag_graph.ainvoke({"request": request, "user_id": 1})

        result = state["result"]
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.warnings)


class RagRetrievalTests(unittest.IsolatedAsyncioTestCase):
    class FakeStore:
        config = SimpleNamespace(content_field="text", index_name="test-index")

        def __init__(self, results):
            self.index = SimpleNamespace(
                query=lambda query: results,
                info=lambda: {
                    "attributes": [
                        ["identifier", field]
                        for field in (
                            "text",
                            "embedding",
                            "_index_name",
                            "_metadata_json",
                            "category",
                            "num",
                            "user_id",
                            "document_id",
                            "source",
                        )
                    ]
                },
            )

        def similarity_search_with_score(self, query, k, filter):
            return [
                (
                    Document(
                        page_content="向量检索内容",
                        metadata={
                            "document_id": "doc-1",
                            "chunk_index": 0,
                            "source": "rag.md",
                        },
                    ),
                    0.25,
                )
            ]

    async def test_vector_and_bm25_results_are_normalized(self):
        fake_store = self.FakeStore(
            [
                {
                    "text": b"BM25 content",
                    "_metadata_json": b'{"document_id":"doc-1","chunk_index":1}',
                    "score": "2.5",
                }
            ]
        )
        task = RetrievalTask(
            task_id="main:vector",
            query="RAG",
            query_kind="main",
            channel="vector",
        )
        bm25_task = task.model_copy(update={"task_id": "main:bm25", "channel": "bm25"})

        with patch(
            "backend.agent.rag_retrieval._get_vector_store",
            return_value=fake_store,
        ):
            vector_chunks = await vector_search(
                task,
                user_id=1,
                filters=RagFilters(),
                limit=5,
            )
            bm25_chunks = await bm25_search(
                bm25_task,
                user_id=1,
                filters=RagFilters(),
                limit=5,
            )

        self.assertEqual(vector_chunks[0].metadata["_retrieval_task_id"], "main:vector")
        self.assertEqual(vector_chunks[0].retrieval_source, "vector")
        self.assertEqual(bm25_chunks[0].content, "BM25 content")
        self.assertEqual(bm25_chunks[0].metadata["_retrieval_task_id"], "main:bm25")
        self.assertEqual(bm25_chunks[0].retrieval_score, 2.5)

    async def test_missing_required_index_fields_raise_clear_error(self):
        fake_store = self.FakeStore([])
        fake_store.config = SimpleNamespace(
            content_field="text",
            index_name="missing-index",
        )
        fake_store.index.info = lambda: {
            "attributes": [
                ["identifier", "text"],
                ["identifier", "embedding"],
                ["identifier", "_index_name"],
                ["identifier", "_metadata_json"],
                ["identifier", "category"],
                ["identifier", "num"],
            ]
        }
        task = RetrievalTask(
            task_id="main:vector",
            query="RAG",
            query_kind="main",
            channel="vector",
        )

        with patch(
            "backend.agent.rag_retrieval._get_vector_store",
            return_value=fake_store,
        ):
            with self.assertRaisesRegex(RuntimeError, "缺少字段"):
                await vector_search(
                    task,
                    user_id=1,
                    filters=RagFilters(),
                    limit=5,
                )


if __name__ == "__main__":
    unittest.main()
