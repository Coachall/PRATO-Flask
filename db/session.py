from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()
# Replace 'your_connection_string' with your actual PostgreSQL connection string
connection_string = os.getenv("DATABASE_URL")

engine = create_engine(connection_string)
Base = declarative_base()
Session = sessionmaker(bind=engine)
