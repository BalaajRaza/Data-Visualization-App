from sql_connector import get_connection

filter_state = {
    "year": [],
    "month": [],
    "department": [],
    "incident_type": [],
    "severity": [],
    "injured": [],
    "days_lost": []
}

def fetch_kpi_data_with_filters():
    conn = get_connection()
    cursor = conn.cursor()

    base_conditions = []
    params = []

    # Handle multiple selections for each filter
    def handle_filter(field, column_name, cast_type=None):
        values = filter_state.get(field)
        if values:
            placeholders = ', '.join(['%s'] * len(values))
            base_conditions.append(f"{column_name} IN ({placeholders})")
            if cast_type:
                params.extend([cast_type(v) for v in values])
            else:
                params.extend(values)

    handle_filter("year", "YEAR(inc_date)", int)
    handle_filter("month", "MONTH(inc_date)", int)
    handle_filter("department", "department")
    handle_filter("incident_type", "incident_type")
    handle_filter("severity", "severity", int)
    handle_filter("injured", "injured", int)
    handle_filter("days_lost", "days_lost", int)

    where_clause = " AND ".join(base_conditions)
    if where_clause:
        where_clause = "WHERE " + where_clause

    final_query = f"""
        SELECT
            COUNT(*) AS total_incidents,
            SUM(CASE WHEN injured=1 THEN 1 ELSE 0 END) AS total_injuries,
            SUM(days_lost) AS total_days_lost,
            ROUND(AVG(severity), 2) AS avg_severity,
            SUM(CASE WHEN severity >= 4 THEN 1 ELSE 0 END) AS high_severity_incidents,
            ROUND((SUM(CASE WHEN injured=1 THEN 1 ELSE 0 END) / COUNT(*)) * 100, 1) AS injury_rate,
            (
                SELECT incident_type
                FROM (
                    SELECT incident_type, COUNT(*) AS count
                    FROM incidents
                    {where_clause}
                    GROUP BY incident_type
                    ORDER BY count DESC
                    LIMIT 1
                ) AS sub
            ) AS most_common_incident_type
        FROM incidents
        {where_clause};
    """

    # Double the params because the subquery also uses the same filters
    cursor.execute(final_query, params * 2)
    result = cursor.fetchone()

    cursor.close()
    conn.close()

    return {
        "total": result[0] or 0,
        "injuries": result[1] or 0,
        "days_lost": result[2] or 0,
        "avg_severity": result[3] or 0.0,
        "high_severity": result[4] or 0,
        "injury_rate": result[5] or 0.0,
        "common_type": result[6] or "N/A"
    }
