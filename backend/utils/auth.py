#整合 根据Token查询用户，返回用户
from fastapi import Header, Depends, HTTPException
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status
from backend.config.mysql_config import get_db
from backend.crud import users


async def get_current_user(
        authorization:str = Header(...,alias='Authorization'),
        db :AsyncSession =Depends(get_db)
):
    token =authorization.replace("Bearer ","")
    user =await users.get_user_by_token(db,token)
    if not user:
        #需要加入一层前端返回令牌失效的反馈
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效的令牌已经过期的令牌")

    return user


from passlib.context import CryptContext

#创建密码上下文
pwd_context=CryptContext(schemes=["bcrypt"],deprecated='auto')

#密码加密
def get_hash_password(password:str):
    return pwd_context.hash(password)
#密码验证：verify返回值是布尔类型
def verify_password(plain_password,hashed_password):
    return pwd_context.verify(plain_password,hashed_password)