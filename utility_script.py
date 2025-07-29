from bokeh.plotting import figure
from bokeh.embed import components
from bokeh.models import ColumnDataSource, HoverTool , Legend , FactorRange , LegendItem , LabelSet
from bokeh.palettes import Category10, Category20
from bokeh.transform import factor_cmap
from bokeh.io.export import export_png
from bokeh.layouts import gridplot
from bokeh.plotting import output_file, save
from bokeh.resources import INLINE
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver
from bokeh.io.webdriver import create_chromium_webdriver
import tempfile
from selenium import webdriver
from PIL import Image
import os
import re

import numpy as np
import pandas as pd
from math import pi
from bokeh.transform import cumsum
import pandas as pd
from sql_connector import get_connection
from datetime import datetime
import secrets, hashlib, binascii

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.lib.units import cm
from PIL import Image
from datetime import datetime

filter_state = {
    "year": [],
    "month": [],
    "department": [],
    "incident_type": [],
    "severity": [],
    "injured": [],
    "days_lost": []
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
    days_lost_vals = fetch_values("SELECT DISTINCT days_lost FROM incidents where days_lost <> (-1)")

    months = sorted(months, key=lambda x: int(x))
    cursor.close()
    conn.close()
    result = {
        "year": years if years else "None",
        "month": months if months else "None",
        "department": departments if departments else "None",
        "incident_type": incident_types if incident_types else "None",
        "severity":  severities if severities else "None",
        "injured":  injured_vals if injured_vals else "None",
        "days_lost": days_lost_vals if days_lost_vals else "None"
    }

    return result


def build_filter_conditions():
    base_conditions = []
    params = []

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

    return where_clause, params

#Incidents Overview KPI Data
def incidents_overview_kpi_data():
    conn = get_connection()
    cursor = conn.cursor()

    where_clause, params = build_filter_conditions()

    query = f"""
        SELECT
            COUNT(*) AS total_incidents,
            SUM(CASE WHEN injured=1 THEN 1 ELSE 0 END) AS total_injuries,
            SUM(days_lost) AS total_days_lost
        FROM incidents
        {where_clause};
    """

    cursor.execute(query, params)
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    return {
        "total": result[0] or 0,
        "injuries": result[1] or 0,
        "days_lost": result[2] or 0
    }

def fetch_incidents_over_time_data():
    conn = get_connection()
    where_clause, params = build_filter_conditions()
    query = f"""
        SELECT DATE_FORMAT(inc_date, '%Y-%m') AS month_start, COUNT(*) AS total_incidents
        FROM incidents
        {where_clause}
        GROUP BY month_start ORDER BY month_start;
    """
    df = pd.read_sql(query, conn, params=params)
    df["month_start"] = pd.to_datetime(df["month_start"])
    conn.close()
    return df

def fetch_injury_split_over_time_data():
    conn = get_connection()
    where_clause, params = build_filter_conditions()
    print("\n\n\n\n\n FILTERS   ", filter_state, "\n\n\n\n\n")
    query = f"""
        SELECT DATE_FORMAT(inc_date, '%Y-%m') AS month_start,
               SUM(CASE WHEN injured = 1 THEN 1 ELSE 0 END) AS injured,
               SUM(CASE WHEN injured = 0 THEN 1 ELSE 0 END) AS not_injured
        FROM incidents
        {where_clause}
        GROUP BY month_start ORDER BY month_start;
    """
    df = pd.read_sql(query, conn, params=params)
    df["month_start"] = pd.to_datetime(df["month_start"])
    conn.close()
    return df

def plot_incidents_over_time(df):
    p = figure(title="Incidents Over Time", x_axis_type="datetime", height=400, width=500,
               tools="pan,wheel_zoom,box_zoom,reset,save")  # exclude 'help'

    p.toolbar.logo = None  # remove Bokeh logo

    source = ColumnDataSource(df)

    line = p.line(x="month_start", y="total_incidents", source=source,
                  line_width=3, color=Category10[10][0])
    circle = p.circle(x="month_start", y="total_incidents", source=source,
                      size=6, color=Category10[10][0])

    legend = Legend(items=[("Incidents", [line, circle])], location="center")
    p.add_layout(legend, 'below')
    p.legend.click_policy = "hide"

    p.add_tools(HoverTool(
        tooltips=[("Month", "@month_start{%b %Y}"), ("Incidents", "@total_incidents")],
        formatters={'@month_start': 'datetime'},
        mode='vline'
    ))

    p.xaxis.axis_label = "Date"
    p.yaxis.axis_label = "Total Incidents"
    return p


def plot_injury_comparison_over_time(df):
    p = figure(title="Injury vs No Injury Over Time", x_axis_type="datetime", height=425, width=480,
               tools="pan,wheel_zoom,box_zoom,reset,save")  # exclude 'help'

    p.toolbar.logo = None  # remove Bokeh logo

    source = ColumnDataSource(df)

    injured_line = p.line(x="month_start", y="injured", source=source,
                          line_width=3, color=Category10[10][1])
    injured_circle = p.circle(x="month_start", y="injured", source=source,
                              size=6, color=Category10[10][1])

    not_injured_line = p.line(x="month_start", y="not_injured", source=source,
                              line_width=3, color=Category10[10][2])
    not_injured_circle = p.circle(x="month_start", y="not_injured", source=source,
                                  size=6, color=Category10[10][2])

    legend = Legend(items=[
        ("Injured", [injured_line, injured_circle]),
        ("Not Injured", [not_injured_line, not_injured_circle])
    ], location="center")

    p.add_layout(legend, 'below')
    p.legend.click_policy = "hide"

    p.add_tools(HoverTool(tooltips=[
        ("Month", "@month_start{%b %Y}"),
        ("Injured", "@injured"),
        ("Not Injured", "@not_injured")
    ], formatters={'@month_start': 'datetime'}, mode='vline'))

    p.xaxis.axis_label = "Date"
    p.yaxis.axis_label = "Number of Incidents"
    return p


def get_incident_overview_figures():
    df1 = fetch_incidents_over_time_data()
    df2 = fetch_injury_split_over_time_data()
    fig1 = plot_incidents_over_time(df1)
    fig2 = plot_injury_comparison_over_time(df2)
    return fig1, fig2


# ------ DEPARTMENTS OVER DATA ------ #

def departments_overview_kpis():
    conn = get_connection()
    cursor = conn.cursor()

    where_clause, params = build_filter_conditions()

    # Incidents by department
    query_by_department = f"""
        SELECT department, COUNT(*) AS total
        FROM incidents
        {where_clause}
        GROUP BY department;
    """

    # Department with most incidents
    query_most_incidents = f"""
        SELECT department, COUNT(*) AS cnt
        FROM incidents
        {where_clause}
        GROUP BY department
        ORDER BY cnt DESC
        LIMIT 1;
    """

    # Department with most injuries
    query_most_injuries = f"""
        SELECT department, COUNT(*) AS injury_count
        FROM incidents
        WHERE injured = 1
        {"AND " + where_clause[6:] if where_clause else ""}
        GROUP BY department
        ORDER BY injury_count DESC
        LIMIT 1;
    """

    cursor.execute(query_by_department, params)
    dept_rows = cursor.fetchall()
    dept_wise_counts = {row[0]: row[1] for row in dept_rows}

    cursor.execute(query_most_incidents, params)
    row1 = cursor.fetchone()
    most_incidents_dept = row1[0] if row1 else "N/A"

    cursor.execute(query_most_injuries, params)
    row2 = cursor.fetchone()
    most_injuries_dept = row2[0] if row2 else "N/A"

    cursor.close()
    conn.close()

    result = {
        "by_department": dept_wise_counts,             
        "most_incidents_dept": most_incidents_dept,      
        "most_injuries_dept": most_injuries_dept          
    }

    return result

def fetch_incidents_by_department():
    conn = get_connection()
    where_clause, params = build_filter_conditions()

    query = f"""
        SELECT department, COUNT(*) AS total
        FROM incidents
        {where_clause}
        GROUP BY department;
    """

    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def fetch_department_vs_severity():
    conn = get_connection()
    where_clause, params = build_filter_conditions()

    query = f"""
        SELECT department, severity, COUNT(*) AS count
        FROM incidents
        {where_clause}
        GROUP BY department, severity
        ORDER BY department, severity;
    """

    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df


def plot_incidents_donut_chart(df):
    df['angle'] = df['total'] / df['total'].sum() * 2 * pi

    if len(df) <= 10:
        palette = Category10[max(3, len(df))][:len(df)]
    else:
        palette = (Category10[10] * ((len(df) // 10) + 1))[:len(df)]

    df['color'] = palette
    df['total'] = pd.to_numeric(df['total'], errors='coerce').fillna(0)
    if df['total'].sum() == 0:
        return blank_chart("No Data")  # gracefully return a blank chart

    df['percentage'] = (df['total'] / df['total'].sum() * 100).round(1).astype(str) + '%'


    df['label_angle'] = df['angle'].cumsum() - df['angle'] / 2

    source = ColumnDataSource(df)

    p = figure(
        title="Incidents Distribution by Department",
        height=500, width=500,
        tools="hover,pan,box_zoom,wheel_zoom,reset,save",
        toolbar_location="above"
    )
    p.toolbar.logo = None
    
    p.x_range.start = -1
    p.x_range.end = 1
    p.y_range.start = 0
    p.y_range.end = 2
    p.match_aspect = True

    # Draw donut wedges
    wedges = p.annular_wedge(
        x=0, y=1, inner_radius=0.4, outer_radius=0.8,
        start_angle=cumsum('angle', include_zero=True),
        end_angle=cumsum('angle'),
        line_color="white", fill_color='color',
        source=source
    )


    # Hover tooltip
    hover = p.select_one(HoverTool)
    hover.tooltips = [
        ("Department", "@department"),
        ("Incidents", "@total"),
        ("Percent", "@percentage")
    ]

    # Remove grid and axes
    p.axis.visible = False
    p.grid.visible = False

    # --- Create custom legend ---
    legend_items = []
    for i, dept in enumerate(df['department']):
        r = p.rect(x=[None], y=[None], width=0, height=0, fill_color=palette[i])
        legend_items.append(LegendItem(label=dept, renderers=[r]))

    legend = Legend(items=legend_items, location="center")
    legend.orientation = "horizontal"
    legend.label_text_font_size = "9pt"
    p.add_layout(legend, 'below')

    return p

def plot_department_vs_severity_bar(df):
    from bokeh.transform import factor_cmap
    departments = sorted(df['department'].unique())
    severities = sorted(df['severity'].astype(str).unique(), key=lambda x: int(x))  # <-- FIXED

    df["x"] = list(zip(df["department"], df["severity"].astype(str)))  # Also cast here for safety

    source = ColumnDataSource(df)
    p = figure(x_range=FactorRange(*df["x"]), height=450, width=900,
            title="Department vs Incident Count by Severity",
            tools="pan,box_zoom,wheel_zoom,reset,save")

    p.toolbar.logo = None

    n = len(severities)
    if n < 3:
        palette = ["#1f77b4", "#ff7f0e"][:n]  # fallback 1-2 colors
    elif n <= 10:
        palette = Category10[n]
    elif n <= 20:
        palette = Category20[n]
    else:
        palette = Category20[20]

    p.vbar(x='x', top='count', width=0.8, source=source,
        fill_color=factor_cmap('x',
                                palette=palette,
                                factors=severities, start=1, end=2))

    p.xaxis.major_label_orientation = pi/4
    p.xaxis.axis_label = "Department / Severity"
    p.yaxis.axis_label = "Incident Count"

    hover = HoverTool(tooltips=[
        ("Department", "@x"),
        ("Count", "@count")
    ])
    p.add_tools(hover)

    return p

def get_department_overview_figures():
    dept_df = fetch_incidents_by_department()
    dept_vs_severity_df = fetch_department_vs_severity()
    donut_chart = plot_incidents_donut_chart(dept_df)
    bar_chart = plot_department_vs_severity_bar(dept_vs_severity_df)
    return donut_chart, bar_chart


# ------ INCIDENT TYPES OVERVIEW ------ #
def incident_types_overview_kpis():
    conn = get_connection()
    cursor = conn.cursor()
    where_clause, params = build_filter_conditions()

    # Incidents by type
    query_by_type = f"""
        SELECT incident_type, COUNT(*) AS total
        FROM incidents
        {where_clause}
        GROUP BY incident_type;
    """

    # Most common incident type
    query_most_common = f"""
        SELECT incident_type, COUNT(*) AS cnt
        FROM incidents
        {where_clause}
        GROUP BY incident_type
        ORDER BY cnt DESC
        LIMIT 1;
    """

    # Most severe incident type
    query_most_severe = f"""
        SELECT incident_type, SUM(severity) AS total_severity
        FROM incidents
        {where_clause}
        GROUP BY incident_type
        ORDER BY total_severity DESC
        LIMIT 1;
    """

    cursor.execute(query_by_type, params)
    rows = cursor.fetchall()
    type_wise_counts = {row[0]: row[1] for row in rows}

    cursor.execute(query_most_common, params)
    row1 = cursor.fetchone()
    most_common_type = row1[0] if row1 else "N/A"

    cursor.execute(query_most_severe, params)
    row2 = cursor.fetchone()
    most_severe_type = row2[0] if row2 else "N/A"

    cursor.close()
    conn.close()

    result = {
        "by_type": type_wise_counts,
        "most_common_type": most_common_type,
        "most_severe_type": most_severe_type
    }

    return result


def fetch_incidents_by_type():
    conn = get_connection()
    where_clause, params = build_filter_conditions()

    query = f"""
        SELECT incident_type, COUNT(*) AS total
        FROM incidents
        {where_clause}
        GROUP BY incident_type;
    """

    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def plot_incident_type_donut_chart(df):
    df['angle'] = df['total'] / df['total'].sum() * 2 * pi

    if len(df) <= 10:
        palette = Category10[max(3, len(df))][:len(df)]
    else:
        palette = (Category10[10] * ((len(df) // 10) + 1))[:len(df)]

    df['color'] = palette
    
    df['total'] = pd.to_numeric(df['total'], errors='coerce').fillna(0)
    if df['total'].sum() == 0:
        return blank_chart("No Data")  # gracefully return a blank chart

    df['percentage'] = (df['total'] / df['total'].sum() * 100).round(1).astype(str) + '%'


    df['label_angle'] = df['angle'].cumsum() - df['angle'] / 2

    source = ColumnDataSource(df)

    p = figure(
        title="Incidents Distribution by Type",
        height=500, width=500,
        tools="hover,pan,box_zoom,wheel_zoom,reset,save",
        toolbar_location="above"
    )
    p.toolbar.logo = None

    p.x_range.start = -1
    p.x_range.end = 1
    p.y_range.start = 0
    p.y_range.end = 2
    p.match_aspect = True

    wedges = p.annular_wedge(
        x=0, y=1, inner_radius=0.4, outer_radius=0.8,
        start_angle=cumsum('angle', include_zero=True),
        end_angle=cumsum('angle'),
        line_color="white", fill_color='color',
        source=source
    )

    hover = p.select_one(HoverTool)
    hover.tooltips = [
        ("Incident Type", "@incident_type"),
        ("Incidents", "@total"),
        ("Percent", "@percentage")
    ]

    p.axis.visible = False
    p.grid.visible = False

    legend_items = []
    for i, itype in enumerate(df['incident_type']):
        r = p.rect(x=[None], y=[None], width=0, height=0, fill_color=palette[i])
        legend_items.append(LegendItem(label=itype, renderers=[r]))

    legend = Legend(items=legend_items, location="center")
    legend.orientation = "horizontal"
    legend.label_text_font_size = "9pt"
    p.add_layout(legend, 'below')

    return p



def fetch_incident_type_vs_severity():
    conn = get_connection()
    where_clause, params = build_filter_conditions()

    query = f"""
        SELECT incident_type, severity, COUNT(*) AS count
        FROM incidents
        {where_clause}
        GROUP BY incident_type, severity
        ORDER BY incident_type, severity;
    """

    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df


def plot_incident_type_vs_severity_bar(df):
    from bokeh.transform import factor_cmap
    incident_types = sorted(df['incident_type'].unique())
    severities = sorted(df['severity'].astype(str).unique(), key=lambda x: int(x))

    df["x"] = list(zip(df["incident_type"], df["severity"].astype(str)))
    source = ColumnDataSource(df)

    p = figure(x_range=FactorRange(*df["x"]), height=450, width=900,
            title="Incident Type vs Incident Count by Severity",
            tools="pan,box_zoom,wheel_zoom,reset,save")

    p.toolbar.logo = None

    n = len(severities)
    if n < 3:
        palette = ["#1f77b4", "#ff7f0e"][:n]  # fallback 1-2 colors
    elif n <= 10:
        palette = Category10[n]
    elif n <= 20:
        palette = Category20[n]
    else:
        palette = Category20[20] 

    p.vbar(x='x', top='count', width=0.8, source=source,
        fill_color=factor_cmap('x',
                                palette=palette,
                                factors=severities, start=1, end=2))

    p.xaxis.major_label_orientation = pi/4
    p.xaxis.axis_label = "Incident Type / Severity"
    p.yaxis.axis_label = "Incident Count"

    hover = HoverTool(tooltips=[
        ("Incident Type", "@x"),
        ("Count", "@count")
    ])
    p.add_tools(hover)

    return p

def get_incident_type_overview_figures():
    type_df = fetch_incidents_by_type()
    type_vs_severity_df = fetch_incident_type_vs_severity()
    type_bar_chart = plot_incident_type_donut_chart(type_df)
    type_vs_severity_bar_chart = plot_incident_type_vs_severity_bar(type_vs_severity_df)
    return type_bar_chart, type_vs_severity_bar_chart


def blank_chart(title="No Data"):
    p = figure(height=300, width=400, title=title)
    p.text(x=0.5, y=0.5, text=["No Data to Display"], text_align="center", text_baseline="middle", text_font_size="14pt")
    return p


#     ADMIN DATA SECTION UTILITY FUNCTIONS     #
def insert_incident_record(data):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        query = """
        INSERT INTO incidents (inc_date, department, incident_type, severity, injured, days_lost)
        VALUES (%s, %s, %s, %s, %s, %s)
        """

        cursor.execute(query, (
            data["inc_date"],
            data["department"],
            data["incident_type"],
            data["severity"],
            data["injured"],
            data["days_lost"]
        ))

        conn.commit()
        cursor.close()
        conn.close()
        return True

    except Exception as e:
        print("Insert error:", e)
        return False
    

ALLOWED_DEPARTMENTS = ["Mining", "Maintenance", "Administration", "Logistics", "Processing"]

def validate_excel_file(file_path):
    expected_columns = [
        "Incident Date", "Department", "Incident Type",
        "Severity Level", "Injured", "Days Lost"
    ]

    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        return False, [], f"Failed to read Excel file: {e}"

    if list(df.columns) != expected_columns:
        return False, [], "Incorrect columns in the file."

    valid_records = []
    invalid_records = []

    for index, row in df.iterrows():
        try:
            inc_date = pd.to_datetime(row["Incident Date"], errors='raise')
            department = row["Department"]
            incident_type = str(row["Incident Type"])
            severity = int(row["Severity Level"])
            injured = int(row["Injured"])
            days_lost = int(row["Days Lost"])

            # Validate department
            if department not in ALLOWED_DEPARTMENTS:
                raise ValueError("Invalid department")

            # Validate severity
            if severity < 1 or severity > 5:
                raise ValueError("Severity level out of range")

            # Validate injured
            if injured not in [0, 1]:
                raise ValueError("Injured value must be 0 or 1")

            valid_records.append({
                "inc_date": inc_date,
                "department": department,
                "incident_type": incident_type,
                "severity": severity,
                "injured": injured,
                "days_lost": days_lost
            })

        except Exception as e:
            invalid_records.append((index + 2, str(e)))  # +2: accounting for header and 0-index

    return True, valid_records, invalid_records

def insert_batch_records(records):
    conn = get_connection()
    cursor = conn.cursor()

    query = """
        INSERT INTO incidents (inc_date, department, incident_type, severity, injured, days_lost)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    for record in records:
        cursor.execute(query, (
            record["inc_date"],
            record["department"],
            record["incident_type"],
            record["severity"],
            record["injured"],
            record["days_lost"]
        ))

    conn.commit()
    cursor.close()
    conn.close()


# ------- ADMIN SECTION ------- #
def generate_salt():
    return secrets.token_hex(16)

def hash_password(password, salt, iterations=1000):
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations)
    return binascii.hexlify(hashed).decode() + salt  # hash + salt

def insert_admin(username, email, password):
    """Inserts an admin into the database.
    
    Returns:
        (success: bool, message: str)
    """
    if len(username) < 6:
        return False, "Username must be at least 6 characters."
    if '@' not in email or '.' not in email:
        return False, "Invalid email address."
    if len(password) < 8 or not any(c.isupper() for c in password) \
       or not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
        return False, "Password must be at least 8 characters long and contain upper, lower, and digit."

    salt = generate_salt()
    hashed_password = hash_password(password, salt)

    conn = get_connection()
    if not conn:
        return False, "Database connection failed."

    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO users (user_name, email, user_password, user_role) VALUES (%s, %s, %s, %s)",
            (username, email, hashed_password, "admin")
        )
        conn.commit()
        return True, "Admin inserted successfully."
    except Exception as e:
        conn.rollback()
        if "Duplicate entry" in str(e):
            return False, "Email already exists."
        return False, f"Database error: {e}"
    finally:
        cursor.close()
        conn.close()

def insert_user(username, email, password):
    if len(username) < 6:
        return False, "Username must be at least 6 characters."
    if '@' not in email or '.' not in email:
        return False, "Invalid email address."
    if len(password) < 8 or not any(c.isupper() for c in password) \
       or not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
        return False, "Password must be at least 8 characters long and contain upper, lower, and digit."

    salt = generate_salt()
    hashed_password = hash_password(password, salt)

    conn = get_connection()
    if not conn:
        return False, "Database connection failed."

    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO users (user_name, email, user_password, user_role) VALUES (%s, %s, %s, %s)",
            (username, email, hashed_password, "user")
        )
        conn.commit()
        return True, "User inserted successfully."
    except Exception as e:
        conn.rollback()
        if "Duplicate entry" in str(e):
            return False, "Email already exists."
        return False, f"Database error: {e}"
    finally:
        cursor.close()
        conn.close()


def generate_pdf_report(kpi_sections, filters, generator, graph_path, ai_insights, stream):
    c = canvas.Canvas(stream, pagesize=A4)
    width, height = A4

    # Header
    c.setFillColor(colors.HexColor("#ABC4FF"))
    c.rect(0, height - 60, width, 60, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(colors.black)
    c.drawString(50, height - 40, "EHS Dashboard Report")

    c.setFont("Helvetica", 12)
    c.drawString(50, height - 80, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    c.drawString(50, height - 95, f"Report by: {generator}")
    y = height - 130

    # Filters
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Applied Filters")
    y -= 15
    c.line(50, y, width - 50, y)
    y -= 20

    if all(val in [None, "", [], "None"] for val in filters.values()):
        c.setFont("Helvetica-Oblique", 12)
        c.drawString(60, y, "No filters applied.")
        y -= 20
    else:
        c.setFont("Helvetica", 12)
        for key, val in filters.items():
            if val:
                val_str = ', '.join(val) if isinstance(val, list) else str(val)
                c.drawString(60, y, f"- {key.replace('_', ' ').capitalize()}: {val_str}")
                y -= 15

    for section_title, kpis in kpi_sections.items():
        y -= 30
        if y < 100:
            c.showPage()
            y = height - 80

        # Section Header
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, section_title)
        y -= 15
        c.line(50, y, width - 50, y)
        y -= 25

        bg = True
        for label, value in kpis.items():
            if y < 100:
                c.showPage()
                y = height - 80
            c.setFillColor(colors.whitesmoke if bg else colors.white)
            c.rect(45, y - 3, width - 90, 18, fill=1, stroke=0)
            c.setFillColor(colors.black)
            c.setFont("Helvetica", 12)
            c.drawString(60, y, f"{label}: {value}")
            y -= 20
            bg = not bg

    # Graph Section
    y -= 30
    if y < 300:
        c.showPage()
        y = height - 80

    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.black)
    c.drawString(50, y, "Visualizations")
    y -= 15
    c.line(50, y, width - 50, y)
    y -= 30

    try:
        img = Image.open(graph_path)
        iw, ih = img.size
        aspect = ih / iw
        new_width = width - 100
        new_height = new_width * aspect

        if new_height > y - 50:
            new_height = y - 50
            new_width = new_height / aspect

        c.drawImage(ImageReader(img), 50, y - new_height, width=new_width, height=new_height)
        y -= new_height + 20
    except Exception as e:
        c.setFillColor(colors.red)
        c.drawString(50, y, f"[Error loading graph: {e}]")
        y -= 20

    # AI Insights Page (if provided)
    if ai_insights:
        c.showPage()
        c.setFillColor(colors.HexColor("#ABC4FF"))
        c.rect(0, height - 60, width, 60, stroke=0, fill=1)
        c.setFont("Helvetica-Bold", 18)
        c.setFillColor(colors.black)
        c.drawString(50, height - 40, "AI Analysis")
        y = height - 100
        c.setFont("Helvetica", 12)
        wrapped = simpleSplit(ai_insights, "Helvetica", 12, width - 100)

        for line in wrapped:
            if y < 50:
                c.showPage()
                y = height - 100
            c.drawString(50, y, line)
            y -= 15

    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.grey)
    c.drawString(50, 30, "© EHS Dashboard Report")
    c.setTitle("EHS Dashboard Report")
    c.save()


def combine_dashboard_graphs(save_path: str):
    chrome_path = "D:/Tools/chromedriver/chromedriver.exe"
    chrome_service = ChromeService(executable_path=chrome_path)

    options = Options()
    options.add_argument("--headless=new")  # Use newer headless mode
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=2400,1800")

    # Create a webdriver manually
    driver = webdriver.Chrome(service=chrome_service, options=options)

    fig1, fig2 = get_incident_overview_figures()          # returns 2 Bokeh figures
    fig3, fig4 = get_department_overview_figures()
    fig5, fig6 = get_incident_type_overview_figures()

    # 2. Combine them in a grid
    grid = gridplot([[fig1, fig2], [fig3, fig4], [fig5, fig6]], toolbar_location= None , sizing_mode="fixed")

    # 3. Export to a temporary file
    temp_path = os.path.join("static", "images", "_temp_grid.png")
    try:
        export_png(grid, filename=temp_path,webdriver=driver)
    except Exception as e:
        raise RuntimeError(f"Failed to export Bokeh grid to PNG: {e}")

    # 4. Resize or convert to final format
    img = Image.open(temp_path)
    img.save(save_path)
    os.remove(temp_path)
