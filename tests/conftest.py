import pytest
import sqlalchemy
from click.testing import CliRunner
from jjaljup import Base, DEFAULT_DATABASE_URI, Session, User


@pytest.yield_fixture
def runner():
    runner = CliRunner()
    with runner.isolated_filesystem():
        yield runner


@pytest.fixture
def session_and_runner(runner):
    engine = sqlalchemy.create_engine(DEFAULT_DATABASE_URI)
    Session.configure(bind=engine)
    Base.metadata.create_all(engine)
    return Session(autocommit=True), runner


@pytest.fixture
def session(session_and_runner):
    return session_and_runner[0]
