from __future__ import annotations

from authlib.integrations.flask_client import OAuth
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
migrate = Migrate()
oauth = OAuth()
