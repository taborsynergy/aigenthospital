
import requests
import json
import random
import string

BASE_URL = "http://localhost:8000"  # Assuming the FastAPI app is running on this port

def generate_random_string(length):
    return ''.join(random.choice(string.ascii_letters) for i in range(length))

def generate_random_email():
    return f"{generate_random_string(10)}@{generate_random_string(5)}.com"

def test_happy_path():
    print("--- Testing Happy Path ---")
    data = {
        "practice_name": f"Test Clinic {generate_random_string(5)}",
        "contact_email": generate_random_email(),
        "password": "securepassword123",
        "specialty": "Cardiology",
        "phone": "123-456-7890",
        "plan": "enterprise"
    }
    response = requests.post(f"{BASE_URL}/api/signup", json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
    assert "slug" in response.json()
    assert "chat_url" in response.json()
    assert response.json()["plan"] == "enterprise"
    assert response.json()["monthly_rate"] == 997.0
    print("Happy Path Test Passed!")
    print("-" * 30)

def test_invalid_practice_name():
    print("--- Testing Invalid Practice Name (Empty) ---")
    data = {
        "practice_name": "   ",
        "contact_email": generate_random_email(),
        "password": "securepassword123",
        "specialty": "Cardiology",
    }
    response = requests.post(f"{BASE_URL}/api/signup", json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 400
    assert response.json()["error"] == "Practice name is required."
    print("Invalid Practice Name Test Passed!")
    print("-" * 30)

def test_invalid_specialty():
    print("--- Testing Invalid Specialty (Empty) ---")
    data = {
        "practice_name": f"Test Clinic {generate_random_string(5)}",
        "contact_email": generate_random_email(),
        "password": "securepassword123",
        "specialty": "   ",
    }
    response = requests.post(f"{BASE_URL}/api/signup", json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 400
    assert response.json()["error"] == "Specialty is required."
    print("Invalid Specialty Test Passed!")
    print("-" * 30)

def test_invalid_email():
    print("--- Testing Invalid Email (Empty) ---")
    data = {
        "practice_name": f"Test Clinic {generate_random_string(5)}",
        "contact_email": "   ",
        "password": "securepassword123",
        "specialty": "Cardiology",
    }
    response = requests.post(f"{BASE_URL}/api/signup", json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 400
    assert response.json()["error"] == "Email is required."
    print("Invalid Email Test Passed!")
    print("-" * 30)

def test_short_password():
    print("--- Testing Short Password ---")
    data = {
        "practice_name": f"Test Clinic {generate_random_string(5)}",
        "contact_email": generate_random_email(),
        "password": "short",
        "specialty": "Cardiology",
    }
    response = requests.post(f"{BASE_URL}/api/signup", json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 400
    assert response.json()["error"] == "Password must be at least 6 characters."
    print("Short Password Test Passed!")
    print("-" * 30)

def test_missing_required_fields():
    print("--- Testing Missing Required Fields ---")
    data = {
        "contact_email": generate_random_email(),
        "password": "securepassword123",
        "specialty": "Cardiology",
    }
    response = requests.post(f"{BASE_URL}/api/signup", json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 422 # FastAPI's default for missing required fields in Pydantic models
    print("Missing Required Fields Test Passed!")
    print("-" * 30)

def test_long_inputs():
    print("--- Testing Long Inputs ---")
    long_string = generate_random_string(500)
    data = {
        "practice_name": long_string,
        "contact_email": generate_random_email(),
        "password": "securepassword123",
        "specialty": long_string,
        "phone": long_string,
    }
    response = requests.post(f"{BASE_URL}/api/signup", json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 200 # Assuming long strings are truncated or accepted
    assert "slug" in response.json()
    print("Long Inputs Test Passed!")
    print("-" * 30)


if __name__ == "__main__":
    test_happy_path()
    test_invalid_practice_name()
    test_invalid_specialty()
    test_invalid_email()
    test_short_password()
    test_missing_required_fields()
    test_long_inputs()
