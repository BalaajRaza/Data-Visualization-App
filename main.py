from dearpygui import dearpygui as dpg
from dearpygui.dearpygui import load_image
from sql_connector import get_connection
from PIL import Image
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import cm as cm_mpl

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.lib.units import cm
from datetime import datetime
from reportlab.lib.utils import simpleSplit

import tkinter as tk
from tkinter import filedialog

import requests
import subprocess
import time

import threading


loader_running = False


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



def update_kpis_with_filters():
    kpi = fetch_kpi_data_with_filters()

    dpg.set_item_label("kpi_total_incidents", f"{kpi['total']}\nTotal Incidents")
    dpg.set_item_label("kpi_total_injuries", f"{kpi['injuries']}\nTotal Injuries")
    dpg.set_item_label("kpi_days_lost", f"{kpi['days_lost']}\nDays Lost")
    dpg.set_item_label("kpi_avg_severity", f"{kpi['avg_severity']}\nAvg. Severity")
    dpg.set_item_label("kpi_high_severity", f"{kpi['high_severity']}\nHigh Severity")
    dpg.set_item_label("kpi_injury_rate", f"{kpi['injury_rate']}%\nInjury Rate")
    dpg.set_item_label("kpi_common_type", f"{kpi['common_type']}\nTop Incident")

    update_applied_filters()
    show_all_graphs()
    
def update_applied_filters():
    if dpg.does_item_exist("applied_filter_group"):
        dpg.delete_item("applied_filter_group", children_only=True)

        applied = [f"{key.replace('_', ' ').capitalize()}: {value}"
                   for key, value in filter_state.items() if value]

        if applied:
            combined = " | ".join(applied)
        else:
            combined = "No filters applied"

        dpg.add_text(combined, color=(0,0,0), parent="applied_filter_group" , tag="applied_filters")
        dpg.bind_item_font("applied_filters", font=("RobotoMono-Lights" , 10))
    



# Create filter dropdowns (call this during GUI setup)
def create_filter_controls():
    filter_options = get_filter_options()

    def make_dropdown(label, key):
        def callback(sender, app_data):
            filter_state[key] = app_data if app_data != "None" else None
            update_kpis_with_filters()

        with dpg.group(width=300):
            dpg.add_text(label, color=(0,0,0),tag=f"filter_label{key}")
            dpg.bind_item_font(f"filter_label{key}", font=small_font)
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

# --------------------------------------------------------#
#                       GRAPHS SETUP                      # 
# --------------------------------------------------------#

def fetch_incidents_over_time():
    conn = get_connection()
    cursor = conn.cursor()

    base_query = """
        SELECT DATE_FORMAT(inc_date, '%Y-%m') as month, COUNT(*) as incident_count
        FROM incidents
        WHERE 1=1
    """
    params = []

    # Append filters
    if filter_state["year"] and filter_state["year"] != "None":
        base_query += " AND YEAR(inc_date) = %s"
        params.append(int(filter_state["year"]))

    if filter_state["month"] and filter_state["month"] != "None":
        base_query += " AND MONTH(inc_date) = %s"
        params.append(int(filter_state["month"]))

    if filter_state["department"] and filter_state["department"] != "None":
        base_query += " AND department = %s"
        params.append(filter_state["department"])

    if filter_state["incident_type"] and filter_state["incident_type"] != "None":
        base_query += " AND incident_type = %s"
        params.append(filter_state["incident_type"])

    if filter_state["severity"] and filter_state["severity"] != "None":
        base_query += " AND severity = %s"
        params.append(int(filter_state["severity"]))

    if filter_state["injured"] and filter_state["injured"] != "None":
        base_query += " AND injured = %s"
        params.append(int(filter_state["injured"]))

    if filter_state["days_lost"] and filter_state["days_lost"] != "None":
        base_query += " AND days_lost = %s"
        params.append(int(filter_state["days_lost"]))

    base_query += " GROUP BY month ORDER BY month"

    cursor.execute(base_query, params)
    results = cursor.fetchall()
    cursor.close()
    conn.close()

    if results:
        months, counts = zip(*results)
        return list(months), list(counts)
    return [], []

def fetch_dept_vs_severity():
    conn = get_connection()
    cursor = conn.cursor()
    base_query = """
        SELECT department, severity, COUNT(*) 
        FROM incidents
        WHERE 1=1
    """
    params = []

    # Append filters
    if filter_state["year"] and filter_state["year"] != "None":
        base_query += " AND YEAR(inc_date) = %s"
        params.append(int(filter_state["year"]))

    if filter_state["month"] and filter_state["month"] != "None":
        base_query += " AND MONTH(inc_date) = %s"
        params.append(int(filter_state["month"]))

    if filter_state["department"] and filter_state["department"] != "None":
        base_query += " AND department = %s"
        params.append(filter_state["department"])

    if filter_state["incident_type"] and filter_state["incident_type"] != "None":
        base_query += " AND incident_type = %s"
        params.append(filter_state["incident_type"])

    if filter_state["severity"] and filter_state["severity"] != "None":
        base_query += " AND severity = %s"
        params.append(int(filter_state["severity"]))

    if filter_state["injured"] and filter_state["injured"] != "None":
        base_query += " AND injured = %s"
        params.append(int(filter_state["injured"]))

    if filter_state["days_lost"] and filter_state["days_lost"] != "None":
        base_query += " AND days_lost = %s"
        params.append(int(filter_state["days_lost"]))
    
    base_query += " GROUP BY department, severity ORDER BY department, severity"
    cursor.execute(base_query, params)
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return data

def fetch_incident_type_vs_severity():
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT incident_type, severity, COUNT(*) 
        FROM incidents
        WHERE 1=1
    """
    params = []

    for key, field in [
        ("year", "YEAR(inc_date)"), ("month", "MONTH(inc_date)"),
        ("department", "department"), ("incident_type", "incident_type"),
        ("injured", "injured"), ("days_lost", "days_lost")
    ]:
        if filter_state[key] and filter_state[key] != "None":
            query += f" AND {field} = %s"
            params.append(int(filter_state[key]) if key in ["year", "month", "injured", "days_lost"] else filter_state[key])

    query += " GROUP BY incident_type, severity ORDER BY incident_type, severity"
    cursor.execute(query, params)
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return data



def fetch_severity_vs_days_lost():
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT severity, SUM(days_lost) 
        FROM incidents
        WHERE 1=1
    """
    params = []

    for key, field in [
        ("year", "YEAR(inc_date)"), ("month", "MONTH(inc_date)"),
        ("department", "department"), ("incident_type", "incident_type"),
        ("injured", "injured")
    ]:
        if filter_state[key]:
            query += f" AND {field} = %s"
            params.append(int(filter_state[key]) if key in ["year", "month", "injured"] else filter_state[key])

    query += " GROUP BY severity ORDER BY severity"
    cursor.execute(query, params)
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return data

def plot_all_graphs():
    months, counts = fetch_incidents_over_time()
    dept_data = fetch_dept_vs_severity()
    type_data = fetch_incident_type_vs_severity()
    sev_days_data = fetch_severity_vs_days_lost()

    fig, axs = plt.subplots(2, 2, figsize=(16, 12))
    fig.tight_layout(pad=8.0)  # Increase spacing between graphs

    # Plot 1: Incidents vs Time
    if months:
        axs[0, 0].plot(months, counts, marker='o', color='#023E8A')
        axs[0, 0].set_title("Incidents Over Time", fontsize=12, color='#023E8A')
        axs[0, 0].tick_params(axis='x', rotation=30)
    else:
        axs[0, 0].set_title("No Data", fontsize=12)
    axs[0, 0].set_xlabel("Year-Month")
    axs[0, 0].set_ylabel("Incident Count")
    axs[0, 0].grid(True)

    # Plot 2: Department vs Severity
    if dept_data:
        import pandas as pd
        df = pd.DataFrame(dept_data, columns=["Department", "Severity", "Count"])
        pivot = df.pivot(index="Department", columns="Severity", values="Count").fillna(0)
        pivot.plot(kind="bar", stacked=True, ax=axs[0, 1], colormap="Blues")
        axs[0, 1].set_title("Departments vs Severity", fontsize=12, color='#023E8A')
        axs[0, 1].set_ylabel("Incidents Severity Count")
        axs[0, 1].legend(title="Severity Level", fontsize=8)
        axs[0, 1].tick_params(axis='x', rotation=30)
        #axs[0,1].grid(True)
    else:
        axs[0, 1].set_title("No Data", fontsize=12)

    # Plot 3: Incident Type vs Severity
    if type_data:
        df = pd.DataFrame(type_data, columns=["Incident Type", "Severity", "Count"])
        pivot = df.pivot(index="Incident Type", columns="Severity", values="Count").fillna(0)
        pivot.plot(kind="bar", stacked=True, ax=axs[1, 0], colormap="Blues")
        axs[1, 0].set_title("Incident Type vs Severity", fontsize=12, color='#023E8A')
        axs[1, 0].set_ylabel("Incidents Severity Count")
        axs[1, 0].legend(title="Severity Levels", fontsize=8)
        axs[1, 0].tick_params(axis='x' , rotation=360)
        #axs[1,0].grid(True)
    else:
        axs[1, 0].set_title("No Data", fontsize=12)


    if sev_days_data:
        severities, days_lost = zip(*sev_days_data)

        max_sev = max(severities)
        min_sev = min(severities)
        norm_severities = [(s - min_sev) / (max_sev - min_sev) if max_sev != min_sev else 0.5 for s in severities]

        cmap = cm_mpl.get_cmap('Blues')
        colors = [cmap(norm) for norm in norm_severities]

        total_days = sum(days_lost)

        external_labels = [f"{(val/total_days)*100:.1f}% ({val} days)" for val in days_lost]

        axs[1, 1].pie(
            days_lost,
            labels=external_labels,
            labeldistance=1.05,
            colors=colors,
            startangle=160,
            textprops={'fontsize': 10},
            radius=1.2
        )
        axs[1, 1].set_title("Severity vs Days Lost", fontsize=12, color='#023E8A')

        box = axs[1, 1].get_position()
        axs[1, 1].set_position([box.x0 - 0.05, box.y0, box.width, box.height])

        legend_patches = [
            mpatches.Patch(color=colors[i], label=f"{severities[i]}")
            for i in range(len(severities))
        ]
        axs[1, 1].legend(
            handles=legend_patches,
            title="Severity Levels",
            loc='center left',
            bbox_to_anchor=(1.2, 0.9),
            fontsize=9,
            title_fontsize=10
        )

    else:
        axs[1, 1].set_title("No Data", fontsize=12)



    plt.savefig("plots.png")
    plt.close()

def show_all_graphs():
    plot_all_graphs()

    width, height, channels, data = dpg.load_image("plots.png")

    # Add or update texture
    if not dpg.does_item_exist("inc_vs_time_texture"):
        with dpg.texture_registry(show=False):
            dpg.add_static_texture(width=width, height=height, default_value=data, tag="inc_vs_time_texture")
    else:
        dpg.delete_item("inc_vs_time_texture")
        dpg.delete_item("inc_vs_time_image")
            
        with dpg.texture_registry(show=False):
            dpg.add_static_texture(width=width, height=height, default_value=data, tag="inc_vs_time_texture")


    # Add or update image
    if not dpg.does_item_exist("inc_vs_time_image"):
        dpg.add_image("inc_vs_time_texture", width=width, height=height, tag="inc_vs_time_image", parent="graph_container")
    else:
        dpg.configure_item("inc_vs_time_image", texture_tag="inc_vs_time_texture", width=width, height=height)

    if not dpg.does_item_exist("graph_bottom_spacer"):
        dpg.add_spacer(height=0, tag="graph_bottom_spacer", parent="graph_container")
def show_graphs():
    show_all_graphs()

def refresh():
    update_kpis_with_filters()
    show_graphs()

# --------------------------------------------------------#
#                      REPORTS SETUP                      # 
# --------------------------------------------------------#

def generate_pdf_report(kpi_data, filters, generator, graph_path="plots.png", save_as="dashboard_report.pdf"):

    if generator in ["", " ", None]:
        generator = "Unknown"

    c = canvas.Canvas(save_as, pagesize=A4)
    width, height = A4

    # Header background box
    c.setFillColor(colors.HexColor("#ABC4FF"))  # Dark green
    c.rect(0, height - 60, width, 60, stroke=0, fill=1)

    # Title
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(colors.HexColor("#000000"))
    c.drawString(50, height - 40, "EHS Dashboard Report")

    # Reset fill color for body
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 80, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    c.drawString(50, height - 95, f"Report by: {generator}")

    y = height - 130

    # Section: Filters
    c.setFillColor(colors.HexColor("#000000"))
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Applied Filters")
    y -= 15
    c.setStrokeColor(colors.grey)
    c.line(50, y, width - 50, y)
    y -= 20
    c.setFillColor(colors.black)

    if all(val in [None, "None", ""] for val in filters.values()):
        c.setFont("Helvetica-Oblique", 12)
        c.drawString(60, y, "No filters applied.")
        y -= 20
    else:
        c.setFont("Helvetica", 12)
        for key, val in filters.items():
            if val:
                c.drawString(60, y, f"- {key.replace('_', ' ').capitalize()}: {val}")
                y -= 15

    y -= 10

    # Section: KPIs
    c.setFillColor(colors.HexColor("#000000"))
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "KPI Summary")
    y -= 15
    c.line(50, y, width - 50, y)
    y -= 25

    alt_color = colors.whitesmoke
    normal_color = colors.white
    bg = True
    for label, value in kpi_data.items():
        if y < 100:  # Add page if nearing bottom
            c.showPage()
            y = height - 80

        c.setFillColor(alt_color if bg else normal_color)
        c.rect(45, y - 3, width - 90, 18, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 12)
        c.drawString(60, y, f"{label.replace('_', ' ').capitalize()}: {value}")
        y -= 20
        bg = not bg

    y -= 15

    # Section: Graphs
    c.setFillColor(colors.HexColor("#000000"))
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Visualizations")
    y -= 15
    c.line(50, y, width - 50, y)
    y -= 30

    try:
        image = Image.open(graph_path)
        img_width, img_height = image.size
        aspect = img_height / img_width

        new_width = width - 100
        new_height = new_width * aspect

        if new_height > y - 50:
            new_height = y - 50
            new_width = new_height / aspect

        c.drawImage(ImageReader(image), 50, y - new_height, width=new_width, height=new_height)
        y -= new_height + 20
    except Exception as e:
        c.setFont("Helvetica", 12)
        c.setFillColor(colors.red)
        c.drawString(60, y, f"[Error loading graph image: {e}]")
    
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.grey)
    c.drawString(50, 30, "© EHS Dashboard Report")

    ai_insights = dpg.get_value("ai_insights_storage")
    if ai_insights:
        c.showPage() 

        c.setFont("Helvetica-Bold", 18)
        c.setFillColor(colors.HexColor("#000000"))
        c.drawString(50, height - 60, "AI Analysis")
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 12)

       
        wrapped_lines = simpleSplit(ai_insights, "Helvetica", 12, width - 100)
        y = height - 100

        for line in wrapped_lines:
            if y < 50: 
                c.showPage()
                c.setFont("Helvetica-Bold", 18)
                c.setFillColor(colors.HexColor("#ABC4FF"))
                c.drawString(50, height - 60, "AI Analysis (cont'd)")
                c.setFillColor(colors.black)
                c.setFont("Helvetica", 12)
                y = height - 100
            c.drawString(50, y, line)
            y -= 15

    # Footer
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.grey)
    c.drawString(50, 30, "© EHS Dashboard Report")

    c.setTitle("EHS Dashboard Report")
    c.save()
    print(f"[PDF Saved as {save_as}]")

def on_generate_report():

    generator_name = dpg.get_value("report_generator_input")
    print(generator_name)

    root = tk.Tk()
    root.withdraw() 

    file_path = filedialog.asksaveasfilename(
        defaultextension=".pdf",
        filetypes=[("PDF files", "*.pdf")],
        title="Save Report As"
    )
    root.destroy()

    if file_path:
        generate_pdf_report(
            kpi_data=fetch_kpi_data_with_filters(),
            filters=filter_state,
            generator=generator_name,
            graph_path="plots.png",
            save_as=file_path
        )
    dpg.set_value("report_generator_input", "")

def run_ollama(prompt):
    print(prompt)
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "mistral",
            "prompt": prompt,
            "stream": False
        }
    )
    result = response.json().get("response", "").strip()
    print(result)
    return result


def generate_insights():
    global loader_running

    # Show popup immediately
    dpg.configure_item("insights_popup", show=True)
    dpg.set_value("popup_insights_text", "Generating Insights...")

    loader_running = True
    threading.Thread(target=update_loader_text, daemon=True).start()

    def generate():
        prompt = """
        I am providing you some data from a dashboard to visualize incidents data from a mine. The data is about the incidents being reported
        in EHS (Emergency Health System) of a coal mine. You have to understand the patterns in data and perform the told analysis.
        """

        prompt+=f"\nApplied Filters = {filter_state}\n\n"

        kpi_data = fetch_kpi_data_with_filters()
        prompt += "KPIs Data:\n"
        for key, value in kpi_data.items():
            prompt += f"{key.replace('_', ' ').capitalize()}: {value}\n"

        incident_over_time = fetch_incidents_over_time()
        prompt += f"\nIncidents Over Time Data (YEAR-MONTH , NO.of INCIDENTS): {incident_over_time}\n\n"

        dept_vs_severity = fetch_dept_vs_severity()
        prompt += f"Department vs Severity Data ({"(DEPARTMENT , SEVERITY 1 , No.of Incidents) , (DEPARTMENT , SEVERITY 2 , No.of Incidents)"}): {dept_vs_severity}\n\n"

        incident_vs_severity = fetch_incident_type_vs_severity()
        prompt += f"Incident vs Severity Data({"(INCIDENT TYPE , SEVERITY 1 , No.of Incidents) , (INCIDENT TYPE , SEVERITY 1 , No.of Incidents)"}): {incident_vs_severity}\n\n"

        severity_vs_days_lost = fetch_severity_vs_days_lost()
        prompt += f"Severity vs Days Lost Data (SEVERITY LEVEL , Total Days Lost): {severity_vs_days_lost}\n\n"

        prompt +="""
Using all this data generate Intelligent Meaningfull Insights and suggestions according to the data or incidents happening
I want you to write the insights in natural language not numerical data. You can tell like forexample if the number of incidents 
is increasing or decreasing, which department are most dangerous or maybe which incident types are more dangerous. Don't stick to
to just these insights make your own. Similarly for suggestions you can suggest to the management to take some actions or any suggestion
you find useful.
Provide the response in this format and strictly follow this format : 
1.Insights:

2.Suggestions:

Add line spaces between different sections so that every section is readible. Also don't write stories just be on point say your thing in one line.
Keep the insights and suggestions to be on point.
"""

        response = run_ollama(prompt)

        if response:
            dpg.set_value("ai_insights_storage", response)
        else:
            dpg.set_value("ai_insights_storage",None)

        
        # Stop loader
        global loader_running
        loader_running = False

        dpg.set_value("popup_insights_text", response)

    threading.Thread(target=generate, daemon=True).start()


def update_loader_text():
    count = 0
    while loader_running and dpg.does_item_exist("popup_insights_text"):
        dots = "." * (count % 4)
        dpg.set_value("popup_insights_text", f"Generating Insights{dots}")
        time.sleep(0.5)
        count += 1


def start_ollama_model(model_name = "mistral"):
    try:
        process = subprocess.Popen(
            ["ollama", "run", model_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(5)
        print(f"\n[INFO] Ollama model '{model_name}' started.\n")
    except Exception as e:
        print(f"[ERROR] Failed to start Ollama: {e}")

def is_ollama_running():
    try:
        response = requests.get("http://localhost:11434/api/tags")
        if response.status_code == 200:
            print("ollama running")
            return True
    except:
        print("ollama not running")
        return False
    


dpg.create_context()

# Theme setup (Green and White)
with dpg.theme() as main_theme:
    with dpg.theme_component(dpg.mvAll):
        dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (237, 242, 251), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Text, (0,0,0), category=dpg.mvThemeCat_Core)
        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 8)
        dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 10)
        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 10, 10)

# KPI card buttons
with dpg.theme() as kpi_button_theme:
    with dpg.theme_component(dpg.mvButton):
        dpg.add_theme_color(dpg.mvThemeCol_Button, (182, 204, 254), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (171, 196, 255), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (182, 204, 254), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Text, (0,0,0), category=dpg.mvThemeCat_Core)
        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6)

# Action buttons (Refresh, Get Insights, Clear Filters, etc.)
with dpg.theme() as action_button_theme:
    with dpg.theme_component(dpg.mvButton):
        dpg.add_theme_color(dpg.mvThemeCol_Button, (171, 196, 255), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (171, 196, 255), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (182, 204, 254), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Text, (0,0,0), category=dpg.mvThemeCat_Core)
        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6)

# Combo filter box
with dpg.theme() as combo_theme:
    with dpg.theme_component(dpg.mvCombo):
        dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 12, 6)
        dpg.add_theme_color(dpg.mvThemeCol_Border, (237, 242, 251), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (182, 204, 254), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (171, 196, 255), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (182, 204, 254), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Text, (0,0,0), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Border, (237, 242, 251), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_PopupBg, (182, 204, 254), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Header, (182, 204, 254), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (171, 196, 255), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (171, 196, 255), category=dpg.mvThemeCat_Core)

# Input fields
with dpg.theme() as input_theme:
    with dpg.theme_component(dpg.mvInputText):
        dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (182, 204, 254), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (3, 4, 94), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (182, 204, 254), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Text, (0,0,0), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Border, (182, 204, 254), category=dpg.mvThemeCat_Core)
        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6)
        dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 10, 6)

# Popup for insights
with dpg.theme() as popup_theme:
    with dpg.theme_component(dpg.mvAll):
        dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (237, 242, 251), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_Text, (0,0,0), category=dpg.mvThemeCat_Core)
        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 8)
        dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 10)
        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 10, 10)

# ------------------- FONTS -------------------

with dpg.font_registry() as font_reg:
    large_font = dpg.add_font("RobotoMono-Bold.ttf", 32)
    medium_font = dpg.add_font("RobotoMono-Medium.ttf", 24)
    small_font = dpg.add_font("RobotoMono-Light.ttf", 20)

# ------------------- UI -------------------

with dpg.window(tag="main_window", label="EHS-Incidents", width=1600, height=900, pos=(0, 0)):
    dpg.bind_item_theme("main_window", main_theme)

    dpg.add_spacer(height=10)
    dpg.add_text("EHS - Incident Dashboard", tag="main_heading", color=(0,0,0), indent=600)
    dpg.bind_item_font("main_heading", large_font)

    dpg.add_separator(label = "Filters",indent=0)
    dpg.add_spacer(height=15)

    
    # dpg.add_text("Apply Filters", tag="filter_heading", color=(2, 62, 138))
    # dpg.bind_item_font("filter_heading", medium_font)
    with dpg.group(horizontal=True):
        create_filter_controls()


    # dpg.add_text("Applied Filters:", color=(2, 62, 138) , tag= "applied_filter_heading")
    # dpg.bind_item_font("applied_filter_heading", medium_font)
    
    dpg.add_button(label="Clear Filters", tag="clear_filters", width=150, callback=clear_filters)
    with dpg.group(tag="applied_filter_group"): pass
    


    dpg.add_spacer(height=15)
    dpg.add_separator(label = "KPIs")
    # dpg.add_text("KPI Overview", tag="kpi_heading", color=(2, 62, 138))
    # dpg.bind_item_font("kpi_heading", medium_font)

    dpg.add_spacer(height=15)
    

    with dpg.group(horizontal=True):
        kpi_tags = [
            "kpi_total_incidents", "kpi_total_injuries", "kpi_days_lost",
            "kpi_avg_severity", "kpi_high_severity", "kpi_injury_rate", "kpi_common_type"
        ]
        for tag in kpi_tags:
            dpg.add_button(label="\n...\n" + tag.split("_")[1].replace("_", " ").title(), width=210, height=100, tag=tag)
            dpg.bind_item_font(tag, small_font)
            dpg.bind_item_theme(tag, kpi_button_theme)
    dpg.add_button(label="Refresh", tag="refresh", width=150, callback=refresh)

    dpg.add_spacer(height=15)
    dpg.add_separator(label = "Report")
    dpg.add_spacer(height=15)
    # dpg.add_text("Report Generator", tag="report_generator_label", color=(2, 62, 138))
    # dpg.bind_item_font("report_generator_label", medium_font)

    dpg.add_input_text(tag="report_generator_input", width=300, hint="Enter your name")
    dpg.bind_item_font("report_generator_input", small_font)
    dpg.bind_item_theme("report_generator_input", input_theme)

    dpg.add_button(label="Generate Report", tag="report_button", width=180, height=40, callback=on_generate_report)

    dpg.add_text("", tag="ai_insights_storage", show=False)

with dpg.window(tag="insights_popup", label="AI Insights", width=800, height=450, pos=(300, 100), show=False):
    dpg.bind_item_theme("insights_popup", popup_theme)
    dpg.add_text("", tag="popup_insights_text", wrap=750)
    dpg.bind_item_font("popup_insights_text", small_font)

with dpg.group(tag="graph_container", parent="main_window"):
    dpg.add_spacer(height=15)
    dpg.add_separator(label = "Graphs and Summary" , parent="graph_container")
    dpg.add_spacer(height=15)
    dpg.add_button(label="Get Insights", tag="insights_button", width=180, height=40, callback=generate_insights)
    # dpg.add_text("GRAPHS", tag="graph_heading", color=(2, 62, 138))
    # dpg.bind_item_font("graph_heading", medium_font)

# Apply theme to action buttons
for action_btn in ["clear_filters", "refresh", "report_button", "insights_button"]:
    if dpg.does_item_exist(action_btn):
        dpg.bind_item_theme(action_btn, action_button_theme)

# ------------------- FINAL SETUP -------------------

if not is_ollama_running():
    print("Ollama Not Running")
    start_ollama_model("mistral")

dpg.create_viewport(title="EHS KPI Dashboard", width=1440, height=1000)
dpg.setup_dearpygui()
dpg.show_viewport()

dpg.set_frame_callback(1, update_kpis_with_filters)
dpg.start_dearpygui()
dpg.destroy_context()