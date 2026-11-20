TEST_PASSWORD = "Travel-test-password!45"


def test_valid_login_me_and_logout_revokes_access_token(api_client):
    login = api_client.post(
        "/api/auth/login",
        json={"email": "ERIN@NORTHSTAR.EXAMPLE", "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "escalation_manager"
    api_client.headers["Authorization"] = f"Bearer {body['access_token']}"

    assert api_client.get("/api/auth/me").json()["email"] == "erin@northstar.example"
    assert api_client.post("/api/auth/logout").status_code == 204
    assert api_client.get("/api/auth/me").status_code == 401


def test_invalid_credentials_return_generic_unauthorized_response(api_client):
    wrong_password = api_client.post(
        "/api/auth/login",
        json={"email": "erin@northstar.example", "password": "incorrect password"},
    )
    unknown_user = api_client.post(
        "/api/auth/login",
        json={"email": "unknown@northstar.example", "password": "incorrect password"},
    )

    assert wrong_password.status_code == 401
    assert unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_missing_and_invalid_tokens_are_rejected(api_client):
    api_client.headers.pop("Authorization", None)
    assert api_client.get("/api/tickets").status_code == 401

    api_client.headers["Authorization"] = "Bearer not-a-signed-token"
    assert api_client.get("/api/tickets").status_code == 401


def test_role_restrictions_for_routing_and_ticket_deletion(api_client, login_as):
    ticket = api_client.post(
        "/api/tickets", json={"subject": "Role check", "priority": "normal"}
    ).json()

    assert login_as("alex@northstar.example").status_code == 200
    assert api_client.post(f"/api/tickets/{ticket['id']}/assign").status_code == 403
    assert api_client.delete(f"/api/tickets/{ticket['id']}").status_code == 403

    assert login_as("erin@northstar.example").status_code == 200
    assert api_client.post(f"/api/tickets/{ticket['id']}/assign").status_code == 200
    assert api_client.delete(f"/api/tickets/{ticket['id']}").status_code == 403

    assert login_as("nora@northstar.example").status_code == 200
    assert api_client.delete(f"/api/tickets/{ticket['id']}").status_code == 204


def test_cross_agency_ticket_and_user_access_is_hidden(api_client, login_as):
    ticket = api_client.post(
        "/api/tickets", json={"subject": "Agency boundary", "priority": "normal"}
    ).json()

    assert login_as("owen@southwind.example").status_code == 200
    assert api_client.get("/api/tickets").json() == []
    assert api_client.get(f"/api/tickets/{ticket['id']}").status_code == 404
    assert api_client.get("/api/users", params={"agency_id": 1}).status_code == 403
