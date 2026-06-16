#!/usr/bin/env python3
"""
Script para testar o servidor Flask e diagnosticar problemas
"""

if __name__ == '__main__':
    import os
    import sys
    
    # Verificar se o Flask está instalado
    try:
        import flask
        print("✓ Flask instalado")
    except ImportError:
        print("✗ Flask não instalado. Execute: pip install flask")
        sys.exit(1)
    
    # Verificar if database exists
    if os.path.exists('goiabal.db'):
        print("✓ Banco de dados encontrado (goiabal.db)")
    else:
        print("! Banco de dados não encontrado - será criado ao iniciar")
    
    # Verificar pasta de uploads
    if os.path.exists('uploads'):
        print("✓ Pasta de uploads existe")
    else:
        print("! Pasta de uploads será criada ao iniciar")
    
    # Iniciar o servidor
    print("\n" + "="*50)
    print("Iniciando servidor Flask...")
    print("Acesse: http://localhost:5000")
    print("="*50 + "\n")
    
    from Main import app
    app.run(debug=True, host='0.0.0.0', port=5000)
