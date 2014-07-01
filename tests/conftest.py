import pytest
import sqlalchemy

from jjaljup import Base, Session


@pytest.fixture
def session():
    engine = sqlalchemy.create_engine('sqlite:///:memory:')
    Session.configure(bind=engine)
    Base.metadata.create_all(engine)
    return Session(autocommit=True)
