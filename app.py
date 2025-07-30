from flask import Flask, request, render_template, redirect, url_for, session , flash , jsonify , send_file
from sql_connector import get_connection
import os, secrets, hashlib, binascii, re
import pandas as pd
from io import BytesIO
from utility_script import *
import io
from fpdf import FPDF
from bokeh.embed import json_item
import json
import threading



app = Flask(__name__)

# Generate secret key once and save it
if os.path.exists("app_secret_key"):
    with open("app_secret_key", "r") as f:
        app.secret_key = f.read().strip()
else:
    app.secret_key = secrets.token_hex(32)
    with open("app_secret_key", "w") as f:
        f.write(app.secret_key)


# ----------- Password Hashing Utilities -----------

def generate_salt():
    return secrets.token_hex(16)

def hash_password(password, salt, iterations=1000):
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations)
    return binascii.hexlify(hashed).decode() + salt  # hash + salt (for storage)

def verify_password(stored_hash, input_password, iterations=1000):
    salt = stored_hash[-32:]  # last 32 hex characters = 16 bytes salt
    real_hash = stored_hash[:-32]
    check_hash = hashlib.pbkdf2_hmac('sha256', input_password.encode(), salt.encode(), iterations)
    return real_hash == binascii.hexlify(check_hash).decode()

# ----------- Session Security Utilities ----------- #
from functools import wraps

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("role") != "admin":
            return redirect(url_for('dashboard'))  # or a 403 page
        return f(*args, **kwargs)
    return decorated_function


# ----------- Signup -----------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    errors = {"username": "", "email": "", "password": ""}

    if request.method == "POST":
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        valid = True

        if len(username) < 6:
            errors["username"] = "Username must be at least 6 characters long."
            valid = False

        if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$", password):
            errors["password"] = "Password must be at least 8 characters and contain upper, lower letters and digits."
            valid = False

        conn = get_connection()
        if not conn:
            return "DB connection failed."

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                errors["email"] = "This email is already registered."
                valid = False

            if not valid:
                return render_template("signup.html", errors=errors)

            salt = generate_salt()
            hashed_password = hash_password(password, salt)

            cursor.execute(
                "INSERT INTO users (user_name, email, user_password, user_role) VALUES (%s, %s, %s, %s)",
                (username, email, hashed_password, "user")
            )
            conn.commit()

            # Auto-login
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            session['role'] = user[4]
            session['token'] = hashlib.sha256(os.urandom(32)).hexdigest()
            session.permanent = True
            return redirect('/dashboard')

        except Exception as e:
            print("Signup Error:", e)
            return "Signup failed."

        finally:
            cursor.close()
            conn.close()

    return render_template("signup.html", errors={"username": "", "email": "", "password": ""})


# ----------- Login -----------

@app.route("/", methods=["GET", "POST"])
def login():
    errors = {"email": "", "password": ""}

    if request.method == "POST":
        email = request.form['email']
        password = request.form['password']

        conn = get_connection()
        if not conn:
            return "DB connection failed."

        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()


            if user and verify_password(user['user_password'], password):
                session['user_id'] = user['user_id']
                session['user_name'] = user['user_name']
                session['role'] = user['user_role']
                session['token'] = hashlib.sha256(os.urandom(32)).hexdigest()
                session.permanent = True

                if user['user_role'] == 'user':
                    return redirect(url_for("dashboard"))
                elif user["user_role"] == 'admin':
                    return redirect(url_for("admin_dashboard"))
            else:
                errors["password"] = "Invalid email or password"
                return render_template("login.html", errors=errors)

        except Exception as e:
            print("Login Error:", e)
            return "Login failed."

        finally:
            cursor.close()
            conn.close()

    return render_template("login.html", errors={"email": "", "password": ""})



# ----------- User Dashboard -----------

@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        if request.form.get("clear_filters") == "1":
            for key in filter_state.keys():
                filter_state[key] = []
        else:
            for key in filter_state.keys():
                selected = request.form.getlist(key)
                filter_state[key] = selected if selected else []

    filter_options = get_filter_options()

    # KPIs
    overview_kpis = incidents_overview_kpi_data()
    dept_kpis = departments_overview_kpis()
    type_kpis = incident_types_overview_kpis()

    # Overview Figures (Incidents vs Time, Injury Split)
    fig1, fig2 = get_incident_overview_figures()
    incident_fig1_json = json.dumps(json_item(fig1, "incident-chart"))
    incident_fig2_json = json.dumps(json_item(fig2, "injury-chart"))

    # Department Figures
    dept_donut, dept_bar = get_department_overview_figures()
    dept_donut_json = json.dumps(json_item(dept_donut, "dept-donut"))
    dept_bar_json = json.dumps(json_item(dept_bar, "dept-bar"))

    # Incident Type Figures
    type_donut, type_bar = get_incident_type_overview_figures()
    type_donut_json = json.dumps(json_item(type_donut, "type-donut"))
    type_bar_json = json.dumps(json_item(type_bar, "type-bar"))

    # Applied filters display
    applied = {
        k: [("Yes" if v == '1' else "No") if k == "injured" else v for v in vals]
        for k, vals in filter_state.items() if vals
    }

    return render_template(
        "user_dashboard.html",
        filters=filter_options,
        user=session['user_name'],
        applied_filters=applied,
        filter_state=filter_state,

        # KPIs
        overview_kpis=overview_kpis,
        dept_kpis=dept_kpis,
        type_kpis=type_kpis,

        # JSON for all Bokeh plots
        incident_fig1_json=incident_fig1_json,
        incident_fig2_json=incident_fig2_json,
        dept_donut_json=dept_donut_json,
        dept_bar_json=dept_bar_json,
        type_donut_json=type_donut_json,
        type_bar_json=type_bar_json
    )


@app.route("/update_dashboard", methods=["POST"])
@login_required
def update_dashboard():
    filters = request.get_json()
    for key in filter_state:
        filter_state[key] = filters.get(key, [])

    # KPIs
    overview_kpis = incidents_overview_kpi_data()
    dept_kpis = departments_overview_kpis()
    type_kpis = incident_types_overview_kpis()

    # Charts
    fig1, fig2 = get_incident_overview_figures()
    dept_donut, dept_bar = get_department_overview_figures()
    type_donut, type_bar = get_incident_type_overview_figures()

    with open("incident_fig1_debug.json", "w") as f:
        f.write(json.dumps(json_item(fig2, "incident-chart"), indent=2))

    return jsonify({
        "overview_kpis": {
            "total_incidents": overview_kpis["total"],
            "total_injuries": overview_kpis["injuries"],
            "total_days_lost": overview_kpis["days_lost"],
        },
        "dept_kpis": {
            "total_by_department": dept_kpis["by_department"],
            "most_incidents_department": dept_kpis["most_incidents_dept"],
            "most_injuries_department": dept_kpis["most_injuries_dept"],
        },
        "type_kpis": {
            "total_by_type": type_kpis["by_type"],
            "most_common_type": type_kpis["most_common_type"],
            "most_severe_type": type_kpis["most_severe_type"]
        },
        "incident_fig1": json_item(fig1, "incident-chart"),
        "incident_fig2": json_item(fig2, "injury-chart"),
        "dept_donut": json_item(dept_donut, "dept-donut"),
        "dept_bar": json_item(dept_bar, "dept-bar"),
        "type_donut": json_item(type_donut, "type-donut"),
        "type_bar": json_item(type_bar, "type-bar"),

        "applied_filters": filter_state
    })

@app.route('/generate_report', methods=['POST'])
def generate_report():
    include_insights = 'include_insights' in request.form
    user = session["user_name"]

    # Collect current dashboard data
    # These should be current from your session state or cache
    kpi_sections = {
        "Incidents Overview": {
            "Total Incidents": incidents_overview_kpi_data()["total"],
            "Total Injuries": incidents_overview_kpi_data()["injuries"],
            "Total Days Lost": incidents_overview_kpi_data()["days_lost"],
        },
        "Departments Overview": {
            **departments_overview_kpis()["by_department"],  # e.g., {"Mining": 12, "Admin": 5}
            "Most Incidents Department": departments_overview_kpis()["most_incidents_dept"],  # e.g., "Mining"
            "Most Injuries Department": departments_overview_kpis()["most_injuries_dept"]  # e.g., "Admin"
        },
        "Incident Type Overview": {
            **incident_types_overview_kpis()["by_type"],  # e.g., {"Fall": 6, "Fire": 3}
            "Most Common Incident Type": incident_types_overview_kpis()["most_common_type"],  # e.g., "Fall"
            "Most Severe Incident Type": incident_types_overview_kpis()["most_severe_type"]  # e.g., "Fall"
        }
    }

    # Save current Bokeh graph image to file (if not already rendered)
    graph_image_path = "static/images/dashboard_graphs.png"
    combine_dashboard_graphs(graph_image_path)  # This renders composite PNG of all graphs

    # AI Insights
    insights_text = ""
    if include_insights:
        if INSIGHTS_RESULT["status"] != "done" or not INSIGHTS_RESULT["insights"].strip():
            # Return a JSON error response (AJAX-safe)
            return jsonify({
                "success": False,
                "message": "AI Insights not generated yet. Please generate insights first."
            }), 400
        insights_text = INSIGHTS_RESULT["insights"]

    # Generate PDF to in-memory stream
    file_stream = io.BytesIO()
    generate_pdf_report(kpi_sections,filter_state, user, graph_image_path, insights_text, file_stream)
    file_stream.seek(0)

    return send_file(file_stream, download_name="incident_report.pdf", as_attachment=True)

# ----------- Admin Routes -----------

@app.route("/admin_dashboard", methods=["GET", "POST"])
@login_required
@admin_required
def admin_dashboard():
    if request.method == "POST":
            if request.form.get("clear_filters") == "1":
                for key in filter_state.keys():
                    filter_state[key] = []
            else:
                for key in filter_state.keys():
                    selected = request.form.getlist(key)
                    filter_state[key] = selected if selected else []

    filter_options = get_filter_options()

        # KPIs
    overview_kpis = incidents_overview_kpi_data()
    dept_kpis = departments_overview_kpis()
    type_kpis = incident_types_overview_kpis()

    # Overview Figures (Incidents vs Time, Injury Split)
    fig1, fig2 = get_incident_overview_figures()
    incident_fig1_json = json.dumps(json_item(fig1, "incident-chart"))
    incident_fig2_json = json.dumps(json_item(fig2, "injury-chart"))

    # Department Figures
    dept_donut, dept_bar = get_department_overview_figures()
    dept_donut_json = json.dumps(json_item(dept_donut, "dept-donut"))
    dept_bar_json = json.dumps(json_item(dept_bar, "dept-bar"))

    # Incident Type Figures
    type_donut, type_bar = get_incident_type_overview_figures()
    type_donut_json = json.dumps(json_item(type_donut, "type-donut"))
    type_bar_json = json.dumps(json_item(type_bar, "type-bar"))

    # Applied filters display
    applied = {
        k: [("Yes" if v == '1' else "No") if k == "injured" else v for v in vals]
        for k, vals in filter_state.items() if vals
    }

    return render_template(
        "admin_dashboard.html",
        filters=filter_options,
        user=session['user_name'],
        applied_filters=applied,
        filter_state=filter_state,

        # KPIs
        overview_kpis=overview_kpis,
        dept_kpis=dept_kpis,
        type_kpis=type_kpis,

        # JSON for all Bokeh plots
        incident_fig1_json=incident_fig1_json,
        incident_fig2_json=incident_fig2_json,
        dept_donut_json=dept_donut_json,
        dept_bar_json=dept_bar_json,
        type_donut_json=type_donut_json,
        type_bar_json=type_bar_json
    )

@app.route("/admin_data", methods=["GET", "POST"])
@login_required
@admin_required
def admin_data():
    if request.method == "POST":
        if "inc_date" in request.form:
            data = {
                "inc_date": request.form.get("inc_date"),
                "department": request.form.get("department"),
                "incident_type": request.form.get("incident_type"),
                "severity": request.form.get("severity"),
                "injured": request.form.get("injured"),
                "days_lost": request.form.get("days_lost")
            }

            success = insert_incident_record(data)
            if success:
                flash("Record inserted successfully!", "success")
            else:
                flash("Failed to insert record. Please try again.", "error")

        elif "excel_file" in request.files:
            file = request.files["excel_file"]
            if not file.filename.endswith(".xlsx"):
                flash("Only .xlsx files are supported.", "error")
            else:
                success, valid, discarded = validate_excel_file(file)
                if success and valid:
                    insert_batch_records(valid)
                    flash(f"{len(valid)} records inserted successfully.", "success")
                else:
                    flash("No valid records found to insert.", "error")

                if discarded:
                    session['discarded'] = discarded  # store temporarily

        return redirect(url_for("admin_data")) 

    discarded = session.pop("discarded", [])

    filters = get_filter_options()
    return render_template("admin_data.html", filters=filters, user=session['user_name'], discarded=discarded)


@app.route('/api/incidents', methods=['GET'])
def get_incidents():
    page = int(request.args.get('page', 1))
    per_page = 10
    offset = (page - 1) * per_page

    filters = {
        'year': request.args.get('year'),
        'month': request.args.get('month'),
        'department': request.args.get('department'),
        'incident_type': request.args.get('incident_type'),
        'severity': request.args.get('severity'),
        'injured': request.args.get('injured')
    }

    base_query = """
        SELECT incident_id, inc_date, department, incident_type, severity, injured, days_lost
        FROM incidents
        WHERE 1=1
    """
    conditions = []
    params = []

    if filters['year']:
        conditions.append("YEAR(inc_date) = %s")
        params.append(filters['year'])
    if filters['month']:
        conditions.append("MONTH(inc_date) = %s")
        params.append(filters['month'])
    if filters['department']:
        conditions.append("department = %s")
        params.append(filters['department'])
    if filters['incident_type']:
        conditions.append("incident_type = %s")
        params.append(filters['incident_type'])
    if filters['severity']:
        conditions.append("severity = %s")
        params.append(filters['severity'])
    if filters['injured'] in ['0', '1']:
        conditions.append("injured = %s")
        params.append(filters['injured'])

    if conditions:
        base_query += " AND " + " AND ".join(conditions)

    count_query = f"SELECT COUNT(*) FROM ({base_query}) AS sub"
    data_query = base_query + " ORDER BY inc_date DESC LIMIT %s OFFSET %s"
    data_params = params + [per_page, offset]

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]

    cursor.execute(data_query, data_params)
    rows = cursor.fetchall()
    columns = ['incident_id', 'inc_date', 'department', 'incident_type', 'severity', 'injured', 'days_lost']
    records = [dict(zip(columns, row)) for row in rows]

    cursor.close()
    conn.close()

    print(records[0:10])

    return jsonify({"records": records, "total": total})




@app.route('/export/incidents')
def export_incidents():
    conn = get_connection()
    cursor = conn.cursor()

    # Read filter values from URL query params
    filters = {
        'year': request.args.get('year'),
        'month': request.args.get('month'),
        'department': request.args.get('department'),
        'incident_type': request.args.get('incident_type'),
        'severity': request.args.get('severity'),
        'injured': request.args.get('injured')
    }

    query = "SELECT inc_date, department, incident_type, severity, injured, days_lost FROM incidents WHERE 1=1"
    params = []

    if filters['year']:
        query += " AND YEAR(inc_date) = %s"
        params.append(filters['year'])
    if filters['month']:
        query += " AND MONTH(inc_date) = %s"
        params.append(filters['month'])
    if filters['department']:
        query += " AND department = %s"
        params.append(filters['department'])
    if filters['incident_type']:
        query += " AND incident_type = %s"
        params.append(filters['incident_type'])
    if filters['severity']:
        query += " AND severity = %s"
        params.append(filters['severity'])
    if filters['injured']:
        query += " AND injured = %s"
        params.append(filters['injured'])

    # Fetch data using pandas
    df = pd.read_sql(query, conn, params=params)

    # Convert to Excel file
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    cursor.close()
    conn.close()

    return send_file(output, as_attachment=True, download_name="incidents.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route("/get_incident/<int:incident_id>")
def get_incident(incident_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM incidents WHERE incident_id = %s", (incident_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return jsonify(row)

@app.route("/update_incident/<int:incident_id>", methods=["POST"])
def update_incident(incident_id):
    data = request.form
    conn = get_connection()
    cursor = conn.cursor()
    query = """
    UPDATE incidents SET inc_date=%s, department=%s, incident_type=%s, severity=%s, injured=%s, days_lost=%s
    WHERE incident_id = %s
    """
    cursor.execute(query, (
        data["inc_date"],
        data["department"],
        data["incident_type"],
        data["severity"],
        data["injured"],
        data["days_lost"],
        incident_id
    ))
    conn.commit()
    cursor.close()
    conn.close()
    return '', 204


@app.route("/delete_incident/<int:incident_id>", methods=["POST"])
def delete_incident(incident_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM incidents WHERE incident_id = %s", (incident_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return '', 204

# ----------- Admin Management -----------

@app.route("/admin_management", methods=["GET", "POST"])
@login_required
@admin_required
def admin_management():
    message = None
    success = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        success, message = insert_admin(username, email, password)

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, user_name, email FROM users WHERE user_role = 'admin'")
    admins = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template(
        "admin_management.html",
        user=session["user_name"],
        admins=admins,
        success=success,
        message=message
    )

from flask import jsonify

@app.route("/delete_admin/<int:admin_id>", methods=["POST"])
def delete_admin(admin_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE user_id = %s AND user_role = 'admin'", (admin_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        cursor.close()
        conn.close()


@app.route("/update_admin/<int:admin_id>", methods=["POST"])
def update_admin(admin_id):
    data = request.get_json()
    username = data.get("username", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    if not username or not email:
        return jsonify({"success": False, "error": "Username and email are required."})

    conn = get_connection()
    cursor = conn.cursor()
    try:
        if password:
            salt = generate_salt()
            hashed_password = hash_password(password, salt)
            cursor.execute("""
                UPDATE users
                SET user_name = %s, email = %s, user_password = %s
                WHERE user_id = %s
            """, (username, email, hashed_password, admin_id))
        else:
            cursor.execute("""
                UPDATE users
                SET user_name = %s, email = %s
                WHERE user_id = %s
            """, (username, email, admin_id))

        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        cursor.close()
        conn.close()

# --------------- User Management -----------

@app.route("/user_management", methods=["GET", "POST"])
@login_required
@admin_required
def user_management():
    message = None
    success = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        print(username)
        print(email)
        print(password)

        success, message = insert_user(username, email, password)  # You’ll define this function

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, user_name, email FROM users WHERE user_role = 'user'")
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template(
        "admin_user_management.html",
        user=session["user_name"],
        users=users,
        success=success,
        message=message
    )

@app.route("/delete_user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE user_id = %s AND user_role = 'user'", (user_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        cursor.close()
        conn.close()


# ----------- Insights -----------

INSIGHTS_RESULT = {"status": "idle", "insights": ""}


@app.route('/insights')
def insights_status():
    return render_template('insights.html')

def run_insights_generation():
    INSIGHTS_RESULT["status"] = "pending"
    insights = generate_insights_from_mistral()
    INSIGHTS_RESULT["status"] = "done"
    INSIGHTS_RESULT["insights"] = insights

@app.route('/generate_insights', methods=['POST'])
def trigger_insights():
    if INSIGHTS_RESULT["status"] != "pending":
        threading.Thread(target=run_insights_generation).start()
    return jsonify({"started": True})

@app.route('/insights_progress')
def get_insights_status():
    return jsonify(INSIGHTS_RESULT)

@app.route('/check_insights_status')
def check_insights_status():
    return jsonify({
        "status": INSIGHTS_RESULT.get("status"),
        "insights": INSIGHTS_RESULT.get("insights", "")
    })

# ----------- Logout -----------

@app.before_request
def enforce_session_integrity():
    if 'user_id' in session:
        if not session.get('token'):
            return redirect(url_for('logout'))

@app.route("/logout")
def logout():
    session.clear()
    session.modified = True
    return redirect(url_for("login"))


# ----------- Run App -----------

if __name__ == "__main__":
    app.run(debug=True)
