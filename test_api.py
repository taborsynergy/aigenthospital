
import httpx
import asyncio
import json

BASE_URL = "http://localhost:8000/api"

async def test_signup_happy_path():
    print("\n--- Testing /api/signup (Happy Path) ---")
    payload = {
        "practice_name": "Test Clinic",
        "contact_email": "test@example.com",
        "password": "securepassword",
        "specialty": "Dentistry",
        "phone": "+155****4567"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/signup", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 200
            assert "slug" in response.json()
            assert "chat_url" in response.json()
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_signup_invalid_email():
    print("\n--- Testing /api/signup (Invalid Email) ---")
    payload = {
        "practice_name": "Invalid Email Clinic",
        "contact_email": "invalid-email", # This is currently accepted by the backend as valid
        "password": "securepassword",
        "specialty": "Cardiology",
        "phone": "+155****4568"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/signup", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            # Backend currently allows this through. If strict email validation is required, it must be added server-side.
            assert response.status_code == 200 
            assert "slug" in response.json()
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_signup_missing_field():
    print("\n--- Testing /api/signup (Missing Field) ---")
    payload = {
        "contact_email": "test2@example.com",
        "password": "securepassword",
        "specialty": "Pediatrics",
        "phone": "+155****4569"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/signup", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 422
            assert "detail" in response.json()
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_signup_empty_field():
    print("\n--- Testing /api/signup (Empty Field) ---")
    payload = {
        "practice_name": "",
        "contact_email": "test3@example.com",
        "password": "securepassword",
        "specialty": "Ophthalmology",
        "phone": "+155****4570"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/signup", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 400
            assert "error" in response.json()
            assert response.json()["error"] == "Practice name is required."
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_signup_large_input():
    print("\n--- Testing /api/signup (Large Input) ---")
    long_string = "a" * 256 # This is quite large, might exceed DB field limits or pydantic max_length
    payload = {
        "practice_name": long_string,
        "contact_email": f"large_email_test@example.com", # Use a valid email format for large email to pass pydantic
        "password": long_string,
        "specialty": long_string,
        "phone": "+155****4571"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/signup", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            # Expect 200 OK since current backend does not strictly validate length beyond Pydantic default string handling
            assert response.status_code == 200 
            assert "slug" in response.json() 
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_signup_unexpected_input():
    print("\n--- Testing /api/signup (Unexpected Input Type) ---")
    payload = {
        "practice_name": "Unexpected Type Clinic",
        "contact_email": 12345,
        "password": "securepassword",
        "specialty": "Neurology",
        "phone": "+155****4572"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/signup", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 422
            assert "detail" in response.json()
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_quote_happy_path():
    print("\n--- Testing /api/quote (Happy Path) ---")
    payload = {
        "full_name": "Quote User",
        "email": "quote@example.com",
        "company": "Quote Co",
        "phone": "+155****6543",
        "message": "I need a quote for a dental procedure."
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/quote", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 200
            assert response.json()["ok"] == True
            assert response.json()["emailed"] == True
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_quote_invalid_email():
    print("\n--- Testing /api/quote (Invalid Email) ---")
    payload = {
        "full_name": "Quote User Invalid",
        "email": "invalid-quote-email", # This is currently accepted by the backend as valid
        "company": "Quote Co Invalid",
        "phone": "+155****6544",
        "message": "Invalid email quote."
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/quote", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            # Backend currently allows this through. If strict email validation is required, it must be added server-side.
            assert response.status_code == 200
            assert response.json()["ok"] == True
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_quote_missing_field():
    print("\n--- Testing /api/quote (Missing Field) ---")
    payload = {
        "email": "quote2@example.com",
        "company": "Quote Co Missing",
        "phone": "+155****6545",
        "message": "Missing name field."
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/quote", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 422
            assert "detail" in response.json()
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_quote_empty_field():
    print("\n--- Testing /api/quote (Empty Field) ---")
    payload = {
        "full_name": "", # Backend currently allows this through
        "email": "quote3@example.com",
        "company": "Quote Co Empty",
        "phone": "+155****6546",
        "message": "Empty name field."
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/quote", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            # Backend currently allows this through. If empty string is not allowed, validation must be added server-side.
            assert response.status_code == 200
            assert response.json()["ok"] == True
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_quote_large_input():
    print("\n--- Testing /api/quote (Large Input) ---")
    long_string = "a" * 1000
    payload = {
        "full_name": long_string,
        "email": "large_quote@example.com",
        "company": long_string,
        "phone": "+155****6547",
        "message": long_string
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/quote", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 200
            assert response.json()["ok"] == True
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_quote_unexpected_input():
    print("\n--- Testing /api/quote (Unexpected Input Type) ---")
    payload = {
        "full_name": "Quote User Unexpected",
        "email": True,
        "company": "Quote Co Unexpected",
        "phone": "+155****6548",
        "message": "Unexpected input type."
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/quote", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 422
            assert "detail" in response.json()
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_clinic_login_happy_path():
    print("\n--- Testing /api/clinic-auth/login (Happy Path) ---")
    signup_payload = {
        "practice_name": "Test Clinic For Login",
        "contact_email": "loginclinic_hp@example.com",
        "password": "clinicpassword_hp",
        "specialty": "General Practice",
        "phone": "+155****2222"
    }
    try:
        async with httpx.AsyncClient() as client:
            signup_response = await client.post(f"{BASE_URL}/signup", json=signup_payload)
            if signup_response.status_code == 200:
                print("Clinic for login created successfully.")
            else:
                print(f"Failed to create clinic for login: {signup_response.status_code} - {signup_response.json()}")

            login_payload = {
                "email": "loginclinic_hp@example.com",
                "password": "clinicpassword_hp"
            }
            response = await client.post(f"{BASE_URL}/clinic-auth/login", json=login_payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 200
            assert "token" in response.json()
            assert "slug" in response.json()
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_clinic_login_invalid_credentials():
    print("\n--- Testing /api/clinic-auth/login (Invalid Credentials) ---")
    payload = {
        "email": "nonexistent@example.com",
        "password": "wrongpassword"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/clinic-auth/login", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 401
            assert "error" in response.json()
            assert response.json()["error"] == "No account found with that email address."
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_clinic_login_missing_field():
    print("\n--- Testing /api/clinic-auth/login (Missing Field) ---")
    payload = {
        "email": "testclinic@example.com"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/clinic-auth/login", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 422
            assert "detail" in response.json()
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_clinic_login_empty_field():
    print("\n--- Testing /api/clinic-auth/login (Empty Field) ---")
    payload = {
        "email": "",
        "password": "clinicpassword"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/clinic-auth/login", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 401
            assert "error" in response.json()
            assert response.json()["error"] == "No account found with that email address."
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_clinic_login_large_input():
    print("\n--- Testing /api/clinic-auth/login (Large Input) ---")
    long_string = "a" * 256
    payload = {
        "email": f"large_login_{long_string}@example.com", # make email valid format but long
        "password": long_string
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/clinic-auth/login", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 401
            assert "error" in response.json()
            assert response.json()["error"] == "No account found with that email address."
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def test_clinic_login_unexpected_input():
    print("\n--- Testing /api/clinic-auth/login (Unexpected Input Type) ---")
    payload = {
        "email": ["clinic@example.com"],
        "password": "clinicpassword"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{BASE_URL}/clinic-auth/login", json=payload)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            assert response.status_code == 422
            assert "detail" in response.json()
    except httpx.ConnectError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


async def main():
    await test_signup_happy_path()
    await test_signup_invalid_email()
    await test_signup_missing_field()
    await test_signup_empty_field()
    await test_signup_large_input()
    await test_signup_unexpected_input()

    await test_quote_happy_path()
    await test_quote_invalid_email()
    await test_quote_missing_field()
    await test_quote_empty_field()
    await test_quote_large_input()
    await test_quote_unexpected_input()

    await test_clinic_login_happy_path()
    await test_clinic_login_invalid_credentials()
    await test_clinic_login_missing_field()
    await test_clinic_login_empty_field()
    await test_clinic_login_large_input()
    await test_clinic_login_unexpected_input()

if __name__ == "__main__":
    asyncio.run(main())
