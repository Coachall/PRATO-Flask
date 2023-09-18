from sqlalchemy import Column, Integer, String
from db.session import Base, engine


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String)
    refresh_token = Column(String)
    access_token = Column(String)

    def __init__(self, user_id, refresh_token, access_token):
        self.user_id = user_id
        self.refresh_token = refresh_token
        self.access_token = access_token

    def __repr__(self):
        return f"<User(id={self.id}, user_id='{self.user_id}', refresh_token='{self.refresh_token}', access_token='{self.access_token}')>"

Base.metadata.create_all(engine)
