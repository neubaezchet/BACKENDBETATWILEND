import psycopg2
conn = psycopg2.connect('postgresql://postgres:oVNybDmnUBecMCMSDKNTLzAuUzQMpdKW@metro.proxy.rlwy.net:52010/railway')
cur = conn.cursor()

cur.execute("SELECT count(*) FROM cases WHERE drive_link IS NOT NULL AND drive_link != ''")
print(f"Cases with drive_link: {cur.fetchone()[0]}")

cur.execute("SELECT count(*) FROM case_documents")
print(f"Total documents: {cur.fetchone()[0]}")

cur.execute("SELECT count(*) FROM case_events")
print(f"Total events: {cur.fetchone()[0]}")

cur.execute("SELECT count(*) FROM case_notes")
print(f"Total notes: {cur.fetchone()[0]}")

cur.execute("SELECT count(*) FROM employees")
print(f"Total employees: {cur.fetchone()[0]}")

cur.execute("SELECT count(*) FROM companies")
print(f"Total companies: {cur.fetchone()[0]}")

# Check 2 non-historico cases
cur.execute("SELECT id, serial, cedula, estado, es_historico, procesado FROM cases WHERE es_historico = true LIMIT 5")
print(f"\nes_historico=true cases: {cur.fetchall()}")

cur.execute("SELECT id, serial, cedula, estado, es_historico, procesado, created_at FROM cases ORDER BY created_at DESC LIMIT 5")
print(f"\nLatest 5 cases: {cur.fetchall()}")

conn.close()
