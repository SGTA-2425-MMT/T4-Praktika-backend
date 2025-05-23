#!/usr/bin/env python3
# Prueba de autenticación
import requests
import json
import time

# URL base donde se está ejecutando la API
BASE_URL = "http://localhost:8000"

# Datos para hacer pruebas
test_username = f"testuser_{int(time.time())}"
test_password = "password123"
test_email = f"{test_username}@example.com"

# Test 1: Registro de usuario
print("\n=== Test de Registro ===")
register_data = {
    "username": test_username,
    "email": test_email,
    "password": test_password
}
print(f"Intentando registrar usuario: {test_username}")
try:
    response = requests.post(f"{BASE_URL}/api/auth/register", json=register_data)
    print(f"Status: {response.status_code}")
    print(f"Respuesta: {json.dumps(response.json(), indent=2)}")
    if response.status_code == 201:
        print("✅ Registro exitoso")
    else:
        print("❌ Error en el registro")
except Exception as e:
    print(f"❌ Error en la solicitud: {str(e)}")

# Test 2: Inicio de sesión
print("\n=== Test de Inicio de Sesión ===")
login_data = {
    "username": test_username,
    "password": test_password
}
print(f"Intentando iniciar sesión con: {test_username}")
try:
    # FastAPI espera datos de formulario para OAuth2PasswordRequestForm
    response = requests.post(f"{BASE_URL}/api/auth/token", data=login_data)
    print(f"Status: {response.status_code}")
    print(f"Respuesta: {json.dumps(response.json(), indent=2)}")
    if response.status_code == 200:
        print("✅ Inicio de sesión exitoso")
        token_data = response.json()
        access_token = token_data["access_token"]
        token_type = token_data["token_type"]
        
        # Test 3: Acceso a ruta protegida
        print("\n=== Test de Acceso a Ruta Protegida ===")
        headers = {"Authorization": f"{token_type} {access_token}"}
        print("Intentando acceder a la información del usuario")
        try:
            response = requests.get(f"{BASE_URL}/api/auth/me", headers=headers)
            print(f"Status: {response.status_code}")
            print(f"Respuesta: {json.dumps(response.json(), indent=2)}")
            if response.status_code == 200:
                print("✅ Acceso exitoso a ruta protegida")
            else:
                print("❌ Error en el acceso a ruta protegida")
        except Exception as e:
            print(f"❌ Error en la solicitud: {str(e)}")
    else:
        print("❌ Error en el inicio de sesión")
except Exception as e:
    print(f"❌ Error en la solicitud: {str(e)}")
