#!/usr/bin/env python3
"""
Script para testar a criação de conta
"""
import requests
import json
import time

# Esperar o servidor iniciar
time.sleep(2)

url = 'http://localhost:5000/api/register'

# Dados de teste
data = {
    'nome': 'Teste User',
    'sobrenome': 'Silva',
    'email': 'teste@example.com',
    'senha': 'senha123',
    'tipo': 'visitante'
}

print("="*60)
print("Testando criação de conta")
print("="*60)
print(f"URL: {url}")
print(f"Dados: {data}\n")

try:
    response = requests.post(url, data=data)
    
    print(f"Status Code: {response.status_code}")
    print(f"Headers: {dict(response.headers)}")
    print(f"\nResponse Text:\n{response.text}")
    
    try:
        json_data = response.json()
        print(f"\nResponse JSON:\n{json.dumps(json_data, indent=2, ensure_ascii=False)}")
    except:
        print("\nNão conseguiu fazer parse como JSON")
    
    if response.status_code == 200:
        print("\n✓ Registro criado com sucesso!")
    else:
        print(f"\n✗ Erro na criação: Status {response.status_code}")
        
except Exception as e:
    print(f"✗ Erro na requisição: {e}")
    import traceback
    traceback.print_exc()
