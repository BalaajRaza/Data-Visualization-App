from flask import Flask, request, render_template, redirect, url_for, session , flash , jsonify , send_file
from sql_connector import get_connection
import os, secrets, hashlib, binascii, re
import pandas as pd
from io import BytesIO
from utility_script import *
import io
from fpdf import FPDF
from bokeh.embed import json_item

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

@app.route("/dashboard" , methods = ["GET" , "POST"])
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
    overview_kpis = incidents_overview_kpi_data()
    script, (incident_div, injury_div) = get_incident_overview_graphs()

    dept_kpis = departments_overview_kpis()
    dept_df = fetch_incidents_by_department()
    severity_df = fetch_department_vs_severity()
    donut_fig = plot_incidents_donut_chart(dept_df)
    bar_fig = plot_department_vs_severity_bar(severity_df)
    dept_script, (donut_div, bar_div) = components((donut_fig, bar_fig))

    type_kpis = incident_types_overview_kpis()
    type_df = fetch_incidents_by_type()
    type_severity_df = fetch_incident_type_vs_severity()
    type_donut = plot_incident_type_donut_chart(type_df)
    type_bar = plot_incident_type_vs_severity_bar(type_severity_df)
    type_script, (type_donut_div, type_bar_div) = components((type_donut, type_bar))

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
        
        overview_kpis=overview_kpis,
        incident_script=script,
        incident_div=incident_div, 
        injury_div=injury_div,

        dept_kpis=dept_kpis,
        dept_script=dept_script,
        donut_div=donut_div,
        bar_div=bar_div,

        type_kpis=type_kpis,
        type_script=type_script,
        type_donut_div=type_donut_div,
        type_bar_div=type_bar_div
    )


@app.route("/update_dashboard", methods=["POST"])
@login_required
def update_dashboard():
    data = request.get_json()

    # Update global filter state
    global filter_state
    filter_state = data
    
    print("\n\n\n\n\n\n\n",filter_state)

    # Update KPIs
    overview_kpis = incidents_overview_kpi_data()
    
    dept_kpis = departments_overview_kpis()
    type_kpis = incident_types_overview_kpis()
    print("\n\n\n\n\n\n\n",overview_kpis,"\n\n\n\n\n\n\n",dept_kpis , "\n\n\n\n\n\n\n",type_kpis , "\n\n\n\n\n\n\n")
    # Get updated figures
    fig1, fig2 = get_incident_overview_graphs()
    dept_df = fetch_incidents_by_department()
    severity_df = fetch_department_vs_severity()
    type_df = fetch_incidents_by_type()
    type_severity_df = fetch_incident_type_vs_severity()

    result = jsonify({
        "overview_kpis": overview_kpis,
        "incident_chart": json_item(fig1, "incident_chart"),
        "injury_chart": json_item(fig2, "injury_chart"),
        "donut_chart": json_item(plot_incidents_donut_chart(dept_df), "donut_chart"),
        "bar_chart": json_item(plot_department_vs_severity_bar(severity_df), "bar_chart"),
        "type_donut_chart": json_item(plot_incident_type_donut_chart(type_df), "type_donut_chart"),
        "type_bar_chart": json_item(plot_incident_type_vs_severity_bar(type_severity_df), "type_bar_chart"),
        "dept_kpis": dept_kpis,
        "type_kpis": type_kpis,
        "applied_filters": {
            k: [("Yes" if v == '1' else "No") if k == "injured" else v for v in vals]
            for k, vals in filter_state.items() if vals
        }
    })

    print(result.get_data())

    # Convert Bokeh figs to JSON
    return result


@app.route('/generate_report', methods=['POST'])
def generate_report():
    include_insights = 'include_insights' in request.form
    user = session.get("user", "Unknown User")

    # Placeholder: later you will replace this with actual AI-generated text
    insights_text = "These are your AI-generated insights: [Placeholder content]"

    # Create a PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Incident Report - {user}", ln=True, align='C')

    pdf.ln(10)
    pdf.cell(200, 10, txt="Report Data Placeholder...", ln=True)

    if include_insights:
        pdf.ln(10)
        pdf.multi_cell(0, 10, txt=insights_text)

    # Return as downloadable file
    file_stream = io.BytesIO()
    pdf.output(file_stream)
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
    overview_kpis = incidents_overview_kpi_data()
    script, (incident_div, injury_div) = get_incident_overview_graphs()

    dept_kpis = departments_overview_kpis()
    dept_df = fetch_incidents_by_department()
    severity_df = fetch_department_vs_severity()
    donut_fig = plot_incidents_donut_chart(dept_df)
    bar_fig = plot_department_vs_severity_bar(severity_df)
    dept_script, (donut_div, bar_div) = components((donut_fig, bar_fig))

    type_kpis = incident_types_overview_kpis()
    type_df = fetch_incidents_by_type()
    type_severity_df = fetch_incident_type_vs_severity()
    type_donut = plot_incident_type_donut_chart(type_df)
    type_bar = plot_incident_type_vs_severity_bar(type_severity_df)
    type_script, (type_donut_div, type_bar_div) = components((type_donut, type_bar))

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
        
        overview_kpis=overview_kpis,
        incident_script=script,
        incident_div=incident_div, 
        injury_div=injury_div,

        dept_kpis=dept_kpis,
        dept_script=dept_script,
        donut_div=donut_div,
        bar_div=bar_div,

        type_kpis=type_kpis,
        type_script=type_script,
        type_donut_div=type_donut_div,
        type_bar_div=type_bar_div
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
