import sqlite3
import os

db_path = os.path.join("ASISTENTE GLAMSTORE", "glamstore.db")
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"Connecting to: {db_path}")
    
    # Check for 'Salvo'
    cursor.execute("SELECT id, title, vendor, stock FROM productos WHERE title LIKE '%Salvo%'")
    rows = cursor.fetchall()
    print(f"\n--- Results for 'Salvo' ({len(rows)}) ---")
    for r in rows:
        print(r)

    # Check for 'Elixir'
    cursor.execute("SELECT id, title, vendor, stock FROM productos WHERE title LIKE '%Elixir%'")
    rows = cursor.fetchall()
    print(f"\n--- Results for 'Elixir' ({len(rows)}) ---")
    for r in rows:
        print(r)

    # Check for 'Maison' + 'Salvo' (Vendor + Title)
    cursor.execute("SELECT id, title, vendor, stock FROM productos WHERE vendor LIKE '%Maison%' AND title LIKE '%Salvo%'")
    rows = cursor.fetchall()
    print(f"\n--- Results for Vendor='Maison' + Title='Salvo' ({len(rows)}) ---")
    for r in rows:
        print(r)
        
    conn.close()
except Exception as e:
    print(f"Error: {e}")
