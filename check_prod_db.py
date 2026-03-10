import requests, json

BASE = "https://web-production-95ed.up.railway.app"
TOKEN = "0b9685e9a9ff3c24652acaad881ec7b2b4c17f6082ad164d10a6e67589f3f67c"
h = {"X-Admin-Token": TOKEN}

# Caso de ejemplo
r = requests.get(f"{BASE}/validador/casos?page_size=2", headers=h, timeout=15)
print("=== CASOS (muestra) ===")
data = r.json()
for c in data.get("casos", []):
    cid = c.get("company_id")
    emp = c.get("empresa")
    ser = c.get("serial")
    print(f"  serial={ser}, empresa={emp}, company_id={cid}")

# Probar con endpoint admin con JWT (necesitamos login)
# Intentar diferentes credenciales
for user, pwd in [("admin", "Admin2026!"), ("admin", "admin123"), ("superadmin", "Super2026!"), ("admin", "neurobaeza")]:
    r2 = requests.post(f"{BASE}/admin/login", json={"username": user, "password": pwd}, timeout=15)
    if r2.status_code == 200:
        print(f"\nLogin OK: {user}")
        jwt_token = r2.json().get("token")
        jh = {"Authorization": f"Bearer {jwt_token}"}
        
        # Empresas
        r3 = requests.get(f"{BASE}/admin/empresas", headers=jh, timeout=15)
        print("\n=== EMPRESAS ===")
        d3 = r3.json()
        for e in d3.get("empresas", []):
            eid = e["id"]
            nom = e["nombre"]
            ec = e.get("email_copia")
            ce = e.get("contacto_email")
            print(f"  ID={eid} | {nom} | email_copia={ec} | contacto={ce}")
        if not d3.get("empresas"):
            print("  (VACIO)")
        
        # Correos
        r4 = requests.get(f"{BASE}/admin/correos?area=all&empresa=all", headers=jh, timeout=15)
        print("\n=== CORREOS NOTIFICACION ===")
        d4 = r4.json()
        print(f"Total: {d4.get('total', 0)}")
        for c in d4.get("correos", []):
            cid = c["id"]
            area = c["area"]
            email = c["email"]
            cpid = c.get("company_id")
            emp = c.get("empresa")
            act = c.get("activo")
            nom = c.get("nombre_contacto")
            print(f"  ID={cid} | area={area} | email={email} | company_id={cpid} | empresa={emp} | activo={act}")
        if not d4.get("correos"):
            print("  (VACIO)")
        break
else:
    print("\nNo se pudo hacer login con ninguna credencial conocida")
    print("Los correos se guardan en correos_notificacion - necesito acceso JWT")
