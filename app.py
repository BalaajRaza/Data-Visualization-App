from flask import Flask, request, render_template, redirect, url_for, session
from sql_connector import get_connection
import os, secrets, hashlib, binascii, re
from utility_script import *

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

@app.route("/dashboard")
def dashboard():
    if 'user_name' not in session:
        return redirect(url_for("login"))
    return f"Welcome {session['user_name']}! You are logged in as {session['role']}."


# ----------- Admin Routes -----------

@app.route("/admin_dashboard", methods=["GET", "POST"])
def admin_dashboard():
    if 'user_name' not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

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

@app.route("/admin_data" , methods=["GET", "POST"])
def admin_data():
    return render_template("admin_data.html") 



# ----------- Logout -----------

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ----------- Run App -----------

if __name__ == "__main__":
    app.run(debug=True)
