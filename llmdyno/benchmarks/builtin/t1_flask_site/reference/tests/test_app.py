from app import create_app


def client(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db")}).test_client()


def test_home(tmp_path):
    assert client(tmp_path).get("/").status_code == 200


def test_contact(tmp_path):
    assert client(tmp_path).post("/contact", data={"name": "a", "email": "a@b.co", "message": "m"}).status_code == 302


def test_dashboard_login_required(tmp_path):
    assert client(tmp_path).get("/dashboard").status_code == 302
