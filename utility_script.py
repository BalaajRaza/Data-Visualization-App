from sql_connector import get_connection

filter_state = {
    "year": None,
    "month": None,
    "department": None,
    "incident_type": None,
    "severity": None,
    "injured": None,
    "days_lost": None
}

def get_filter_options():
    conn = get_connection()
    cursor = conn.cursor()

    def fetch_values(query):
        cursor.execute(query)
        return sorted([str(row[0]) for row in cursor.fetchall() if row[0] is not None])

    years = fetch_values("SELECT DISTINCT YEAR(inc_date) FROM incidents")
    months = fetch_values("SELECT DISTINCT MONTH(inc_date) FROM incidents")
    departments = fetch_values("SELECT DISTINCT department FROM incidents")
    incident_types = fetch_values("SELECT DISTINCT incident_type FROM incidents")
    severities = fetch_values("SELECT DISTINCT severity FROM incidents")
    injured_vals = fetch_values("SELECT DISTINCT injured FROM incidents")
    days_lost_vals = fetch_values("SELECT DISTINCT days_lost FROM incidents")

    months = sorted(months, key=lambda x: int(x))
    cursor.close()
    conn.close()

    return {
        "year": ["None"] + years,
        "month": ["None"] + months,
        "department": ["None"] + departments,
        "incident_type": ["None"] + incident_types,
        "severity": ["None"] + severities,
        "injured": ["None"] + injured_vals,
        "days_lost": ["None"] + days_lost_vals
    }


def fetch_kpi_data_with_filters():
    conn = get_connection()
    cursor = conn.cursor()

    base_conditions = []
    params = []

    # Apply filters
    if filter_state["year"]:
        base_conditions.append("YEAR(inc_date) = %s")
        params.append(int(filter_state["year"]))
    if filter_state["month"]:
        base_conditions.append("MONTH(inc_date) = %s")
        params.append(int(filter_state["month"]))
    if filter_state["department"]:
        base_conditions.append("department = %s")
        params.append(filter_state["department"])
    if filter_state["incident_type"]:
        base_conditions.append("incident_type = %s")
        params.append(filter_state["incident_type"])
    if filter_state["severity"]:
        base_conditions.append("severity = %s")
        params.append(int(filter_state["severity"]))
    if filter_state["injured"]:
        base_conditions.append("injured = %s")
        params.append(int(filter_state["injured"]))
    if filter_state["days_lost"]:
        base_conditions.append("days_lost = %s")
        params.append(int(filter_state["days_lost"]))

    where_clause = " AND ".join(base_conditions)
    if where_clause:
        where_clause = "WHERE " + where_clause

    # Final query
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

    cursor.execute(final_query, params * 2) 
    result = cursor.fetchone()

    cursor.close()
    conn.close()

    # Return a dict for clarity
    return {
        "total": result[0] or 0,
        "injuries": result[1] or 0,
        "days_lost": result[2] or 0,
        "avg_severity": result[3] or 0.0,
        "high_severity": result[4] or 0,
        "injury_rate": result[5] or 0.0,
        "common_type": result[6] or "N/A"
    }