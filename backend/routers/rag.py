from fastapi import APIRouter, Depends, HTTPException

from backend.models.users import User
from backend.schemas.rag import RagQuery, RagResult
from backend.services.rag_service import search_knowledge_base
from backend.utils.auth import get_current_user

router = APIRouter(prefix="/api/rag", tags=["rag"])


@router.post("/search", response_model=RagResult)
async def search_rag(
    request: RagQuery,
    user: User = Depends(get_current_user),
):
    """对当前登录用户执行知识库检索，保持现有 RAG 逻辑不变。

    这里是 REST API 层，真正的业务执行由 rag_service 负责。
    """
    try:
        return await search_knowledge_base(request=request, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
