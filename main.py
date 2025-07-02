from dearpygui import dearpygui as dpg
from dearpygui.dearpygui import load_image
from sql_connector import get_connection
from PIL import Image
import numpy as np


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

# --------------------------------------------------------#
#                       KPIs SETUP                        # 
# --------------------------------------------------------#


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

    cursor.execute(final_query, params * 2)  # Used in main query and subquery
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



def update_kpis_with_filters():
    kpi = fetch_kpi_data_with_filters()

    dpg.set_item_label("kpi_total_incidents", f"{kpi['total']}\nTotal Incidents")
    dpg.set_item_label("kpi_total_injuries", f"{kpi['injuries']}\nTotal Injuries")
    dpg.set_item_label("kpi_days_lost", f"{kpi['days_lost']}\nDays Lost")
    dpg.set_item_label("kpi_avg_severity", f"{kpi['avg_severity']}\nAvg. Severity")
    dpg.set_item_label("kpi_high_severity", f"{kpi['high_severity']}\nHigh Severity")
    dpg.set_item_label("kpi_injury_rate", f"{kpi['injury_rate']}%\nInjury Rate")
    dpg.set_item_label("kpi_common_type", f"{kpi['common_type']}\nTop Incident")

# Create filter dropdowns (call this during GUI setup)
def create_filter_controls():
    filter_options = get_filter_options()

    def make_dropdown(label, key):
        def callback(sender, app_data):
            filter_state[key] = app_data if app_data != "None" else None
            update_kpis_with_filters()

        with dpg.group(width=300):
            dpg.add_text(label, color=(0, 102, 68))
        combo_id = dpg.add_combo(
            items=filter_options[key],
            default_value="None",
            width=280,
            callback=callback,
            tag=f"combo_{key}"
        )
        dpg.bind_item_theme(combo_id, combo_theme)

    with dpg.group():  # Outer vertical group to hold rows
        keys = ["year", "month", "department", "incident_type", "severity", "injured", "days_lost"]
        labels = [
            "Year", "Month", "Department",
            "Incident Type", "Severity",
            "Injured (0/1)", "Days Lost"
        ]

        for i in range(0, len(keys), 4):
            with dpg.group(horizontal=True):
                for j in range(4):
                    if i + j < len(keys):
                        make_dropdown(labels[i + j], keys[i + j])
            dpg.add_spacer(height=5)

def clear_filters():
    # Reset filter state
    for key in filter_state:
        filter_state[key] = None

    # Reset combo boxes to "None"
    for key in filter_state:
        dpg.set_value(f"combo_{key}", "None")

    # Refresh KPI cards
    update_kpis_with_filters()




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

with dpg.theme() as combo_theme:
    with dpg.theme_component(dpg.mvCombo):
        dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (225, 255, 225), category=dpg.mvThemeCat_Core)        # Base background
        dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (210, 255, 210), category=dpg.mvThemeCat_Core) # Hover
        dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (200, 240, 200), category=dpg.mvThemeCat_Core)  # Active click
        dpg.add_theme_color(dpg.mvThemeCol_Text, (0, 80, 40), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 120, 80), category=dpg.mvThemeCat_Core)

        dpg.add_theme_color(dpg.mvThemeCol_PopupBg, (240, 255, 240), category=dpg.mvThemeCat_Core)        # List background
        dpg.add_theme_color(dpg.mvThemeCol_Header, (200, 240, 200), category=dpg.mvThemeCat_Core)         # Hovered option
        dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (180, 230, 180), category=dpg.mvThemeCat_Core)  # Hover effect
        dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (160, 220, 160), category=dpg.mvThemeCat_Core)   # Clicked effect

        
        

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
    
    dpg.add_spacer(height=10)
    dpg.add_button(label="Clear Filters", width=150, callback=clear_filters)

    dpg.add_spacer(height=15)
    dpg.add_text("KPI Overview", color=(0, 80, 40))
    dpg.add_spacer(height=10)

    dpg.add_button(label="Refresh KPIs", width=180, callback=update_kpis_with_filters)

    # KPI Cards
    with dpg.group(horizontal=True):
        dpg.add_button(label="\n...\nTotal Incidents", width=200, height=90, tag="kpi_total_incidents")
        dpg.add_button(label="\n...\nTotal Injuries", width=200, height=90, tag="kpi_total_injuries")
        dpg.add_button(label="\n...\nDays Lost", width=200, height=90, tag="kpi_days_lost")
        dpg.add_button(label="\n...\nAvg. Severity", width=200, height=90, tag="kpi_avg_severity")
        dpg.add_button(label="\n...\nHigh Severity", width=200, height=90, tag="kpi_high_severity")

        dpg.add_spacer(height=10)
    with dpg.group(horizontal=True):
        
        dpg.add_button(label="\n...\nInjury Rate", width=200, height=90, tag="kpi_injury_rate")
        dpg.add_button(label="\n...\nTop Incident", width=200, height=90, tag="kpi_common_type")

    


# Viewport setup
dpg.create_viewport(title="EHS KPI Dashboard", width=1440, height=900)
dpg.setup_dearpygui()
dpg.show_viewport()

update_kpis_with_filters()


dpg.start_dearpygui()
dpg.destroy_context()
