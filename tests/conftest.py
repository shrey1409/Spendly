import pytest
from app import app as flask_app


@pytest.fixture
def app(tmp_path):
    flask_app.config['DATABASE'] = str(tmp_path / 'test.db')
    flask_app.config['TESTING'] = True
    with flask_app.app_context():
        from database.db import init_db
        init_db()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()
