# This file just exposes the Base to other modules.
# We will import all models in __init__.py of this module to help Alembic discover them.
from app.database import Base
