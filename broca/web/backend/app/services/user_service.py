import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.user import UserProfile

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str) -> UserProfile | None:
        try:
            user_profile = await self.db.scalar(select(UserProfile).where(UserProfile.id == user_id))
            return user_profile
        except Exception as e:
            logger.error(f"Error getting user by ID {user_id}: {e}")
            raise

    async def create_user_profile(self, data: UserProfile) -> UserProfile:
        try:
            user_profile = UserProfile(**data.model_dump())

            self.db.add(user_profile)

            await self.db.flush()
            logger.debug("User profile added and flushed")

            await self.db.commit()
            logger.debug("Transaction committed successfully")

            await self.db.refresh(user_profile)

            return user_profile
        except Exception as e:
            logger.error(f"Error creating user profile: {e}")
            raise
