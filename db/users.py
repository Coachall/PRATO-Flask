from sqlalchemy import Column, Integer, String
from db.session import Base, engine


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String)
    refresh_token = Column(String)
    access_token = Column(String)
    custom_field_id = Column(String)
    work_type_id = Column(String)

    def __init__(self, user_id, refresh_token, access_token, custom_field_id, work_type_id):
        self.user_id = user_id
        self.refresh_token = refresh_token
        self.access_token = access_token
        self.custom_field_id = custom_field_id
        self.work_type_id = work_type_id

    def __repr__(self):
        return f"<User(id={self.id}, user_id='{self.user_id}', refresh_token='{self.refresh_token}', access_token='{self.access_token}')>"

Base.metadata.create_all(engine)
