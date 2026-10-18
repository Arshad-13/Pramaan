"""P0: the built React app is served from the same origin, safely."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def spa_client(tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>INDEX</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("TOP SECRET")  # outside dist
    with TestClient(create_app(frontend_dist=dist)) as client:
        yield client


def test_root_and_client_routes_fall_back_to_index(spa_client):
    for path in ("/", "/login", "/verify", "/prescriptions/new"):
        response = spa_client.get(path)
        assert response.status_code == 200
        assert "INDEX" in response.text


def test_static_files_are_served(spa_client):
    assert spa_client.get("/assets/app.js").text == "console.log(1)"
    assert spa_client.get("/favicon.svg").text == "<svg/>"


def test_unknown_api_paths_return_json_404_not_the_app(spa_client):
    response = spa_client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_api_still_works_alongside_spa(spa_client):
    assert spa_client.get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/..%2fsecret.txt", "/%2e%2e/secret.txt", "/../secret.txt"])
def test_path_traversal_never_leaks_files_outside_dist(spa_client, path):
    response = spa_client.get(path)
    assert "TOP SECRET" not in response.text


def test_no_frontend_build_means_api_only(tmp_path: Path):
    with TestClient(create_app(frontend_dist=tmp_path / "missing")) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/login").status_code == 404
