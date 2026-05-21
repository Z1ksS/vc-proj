import psycopg2

conn = psycopg2.connect(host='127.0.0.1', port=5433, dbname='jobvc', user='jobvc', password='Xazyb228$')
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM jobs WHERE is_miltech = TRUE")
print('Miltech count:', cur.fetchone()[0])

cur.execute("SELECT title, company FROM jobs WHERE is_miltech = TRUE ORDER BY created_at DESC LIMIT 20")
for title, company in cur.fetchall():
    print(f"  {title} | {company}")

conn.close()
