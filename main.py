from dearpygui import dearpygui as dpg
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

# Fetch filter options from DB
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

    query = "SELECT COUNT(*), SUM(CASE WHEN injured=1 THEN 1 ELSE 0 END), SUM(days_lost), ROUND(AVG(severity), 2) FROM incidents WHERE 1=1"
    params = []

    # Append filters
    if filter_state["year"] and filter_state["year"] != "None":
        query += " AND YEAR(inc_date) = %s"
        params.append(int(filter_state["year"]))

    if filter_state["month"] and filter_state["month"] != "None":
        query += " AND MONTH(inc_date) = %s"
        params.append(int(filter_state["month"]))

    if filter_state["department"] and filter_state["department"] != "None":
        query += " AND department = %s"
        params.append(filter_state["department"])

    if filter_state["incident_type"] and filter_state["incident_type"] != "None":
        query += " AND incident_type = %s"
        params.append(filter_state["incident_type"])

    if filter_state["severity"] and filter_state["severity"] != "None":
        query += " AND severity = %s"
        params.append(int(filter_state["severity"]))

    if filter_state["injured"] and filter_state["injured"] != "None":
        query += " AND injured = %s"
        params.append(int(filter_state["injured"]))

    if filter_state["days_lost"] and filter_state["days_lost"] != "None":
        query += " AND days_lost = %s"
        params.append(int(filter_state["days_lost"]))

    cursor.execute(query, params)
    total_incidents, total_injuries, days_lost, avg_severity = cursor.fetchone()

    cursor.close()
    conn.close()

    return total_incidents or 0, total_injuries or 0, days_lost or 0, avg_severity or 0.0



def update_kpis_with_filters():
    total, injuries, lost, severity = fetch_kpi_data_with_filters()
    dpg.set_item_label("kpi_total_incidents", f"{total}\nTotal Incidents")
    dpg.set_item_label("kpi_total_injuries", f"{injuries}\nTotal Injuries")
    dpg.set_item_label("kpi_days_lost", f"{lost}\nDays Lost")
    dpg.set_item_label("kpi_avg_severity", f"{severity}\nAvg. Severity")

# Create filter dropdowns (call this during GUI setup)
def create_filter_controls():
    filter_options = get_filter_options()

    def make_dropdown(label, key):
        def callback(sender, app_data):
            filter_state[key] = app_data if app_data != "None" else None
            update_kpis_with_filters()

        dpg.add_text(label)
        dpg.add_combo(items=filter_options[key], default_value="None", width=200, callback=callback)

    make_dropdown("Year", "year")
    make_dropdown("Month", "month")
    make_dropdown("Department", "department")
    make_dropdown("Incident Type", "incident_type")
    make_dropdown("by Severity", "severity")
    make_dropdown("Injured ", "injured")
    make_dropdown("Days Lost", "days_lost")


dpg.create_context()

# Theme setup (Green and White)
with dpg.theme() as kpi_theme:
    with dpg.theme_component(dpg.mvAll):
        dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (255, 255, 255), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 153, 102), category=dpg.mvThemeCat_Core)          
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 180, 120), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (0, 120, 90), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Text, (0, 60, 40), category=dpg.mvThemeCat_Core)
        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 8)
        dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 10)
        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 10, 10)
        

# Create main window
with dpg.window(tag="main_window", label="EHS-Incidents", width=1440, height=900, pos=(0, 0)):
    dpg.bind_item_theme("main_window", kpi_theme)

    dpg.add_spacer(height=10)
    dpg.add_text("EHS - Incident Dashboard", color=(0, 102, 68), bullet=False)
    dpg.add_separator()
    dpg.add_spacer(height=15)

    dpg.add_text("Apply Filters", color=(50, 50, 50))
    with dpg.group(horizontal=True):
        create_filter_controls()

    dpg.add_spacer(height=15)
    dpg.add_text("KPI Overview", color=(0, 80, 40))
    dpg.add_spacer(height=10)

    dpg.add_button(label="Refresh KPIs", width=180, callback=update_kpis_with_filters)

    # KPI Cards
    with dpg.group(horizontal=True):
        dpg.add_button(label="\n...\nTotal Incidents", width=210, height=90, tag="kpi_total_incidents")
        dpg.add_button(label="\n...\nTotal Injuries", width=210, height=90, tag="kpi_total_injuries")
        dpg.add_button(label="\n...\nDays Lost", width=210, height=90, tag="kpi_days_lost")
        dpg.add_button(label="\n...\nAvg. Severity", width=210, height=90, tag="kpi_avg_severity")

    


# Viewport setup
dpg.create_viewport(title="EHS KPI Dashboard", width=1440, height=900)
dpg.setup_dearpygui()
dpg.show_viewport()

update_kpis_with_filters()
dpg.start_dearpygui()
dpg.destroy_context()
