from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

client = AsyncIOMotorClient(settings.MONGODB_URI)
# Use default database name from the MongoDB URI or default to 'civgame'
db = client.get_default_database() or client['civgame']