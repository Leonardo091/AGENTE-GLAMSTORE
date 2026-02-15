from archivo_objetivo import funcion_a_probar

def test_caso_basico():
    resultado = funcion_a_probar("entrada")
    assert resultado == "esperado", f"Fallo: {resultado} != esperado"
    print("✅ Test básico pasado")

if __name__ == "__main__":
    test_caso_basico()
