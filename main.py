from sql_connector import get_connection

# Get a connection
conn = get_connection()

if conn:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM incidents LIMIT 5;")
    rows = cursor.fetchall()

    print("📊 Sample Data:")
    for row in rows:
        print(row)

    cursor.close()
    conn.close()
else:
    print("❌ Could not connect to the database.")
