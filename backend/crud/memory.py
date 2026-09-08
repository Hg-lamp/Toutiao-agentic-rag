from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.mysql_config import get_db


async def get_user_memory(user_id:int,db:AsyncSession=Depends(get_db)):
    # stmt = select(Memory.content).where(Memory.user_id == user_id)
    # res = await db.execute(stmt)
    # return res.scalar_one_or_none()
    return "用户住在郑州"