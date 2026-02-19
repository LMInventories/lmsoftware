import sqlite3

conn = sqlite3.connect('instance/inspection_system.db')
cur = conn.cursor()

cur.execute('ALTER TABLE inspections ADD COLUMN report_data TEXT')
cur.execute("ALTER TABLE clients ADD COLUMN logo TEXT")
cur.execute("ALTER TABLE clients ADD COLUMN primary_color VARCHAR(7) DEFAULT '#1E3A8A'")
cur.execute('ALTER TABLE clients ADD COLUMN report_disclaimer TEXT')
cur.execute('ALTER TABLE clients ADD COLUMN report_color_override VARCHAR(7)')

conn.commit()
conn.close()

print('Done')
