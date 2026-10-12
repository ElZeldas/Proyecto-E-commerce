import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
import json
import base64

# Asegurar que se ejecuta en el directorio correcto
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Configurar variables de entorno antes de cargar la aplicación
os.environ["API_HOST"] = "127.0.0.1"
os.environ["API_PORT"] = "8000"

PREFS_FILE = os.path.expanduser("~/.microsip_calc_prefs.json")
SECRET_KEY = "m1cr0s1p_s3cr3t"

def obfuscate(text: str) -> str:
    if not text: return ""
    xored = ''.join(chr(ord(c) ^ ord(k)) for c, k in zip(text, SECRET_KEY * (len(text) // len(SECRET_KEY) + 1)))
    return base64.b64encode(xored.encode('utf-8')).decode('utf-8')

def deobfuscate(text: str) -> str:
    if not text: return ""
    try:
        decoded = base64.b64decode(text.encode('utf-8')).decode('utf-8')
        return ''.join(chr(ord(c) ^ ord(k)) for c, k in zip(decoded, SECRET_KEY * (len(decoded) // len(SECRET_KEY) + 1)))
    except Exception:
        return ""

def load_prefs():
    if os.path.exists(PREFS_FILE):
        try:
            with open(PREFS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_prefs(username, password, save_pwd):
    prefs = {"username": username, "save_pwd": save_pwd}
    if save_pwd:
        prefs["password"] = obfuscate(password)
    else:
        prefs["password"] = ""
    try:
        with open(PREFS_FILE, "w") as f:
            json.dump(prefs, f)
    except Exception:
        pass

def login():
    username = user_entry.get().strip()
    password = pass_entry.get()
    
    if not username or not password:
        messagebox.showwarning("Atención", "Debe ingresar usuario y contraseña.")
        return

    # Deshabilitar botones mientras se verifica
    btn_login.config(state=tk.DISABLED)
    root.update()

    try:
        # Guardar las credenciales en el entorno ANTES de importar módulos del backend
        # para que Pydantic BaseSettings las lea correctamente al instanciarse.
        os.environ["MICROSIP_DB_USER"] = username
        os.environ["MICROSIP_DB_PASSWORD"] = password

        from database import verify_microsip_credentials
        # Intenta conectar y verificar las credenciales
        verify_microsip_credentials(username, password)
        
        # Guardar preferencias locales
        save_prefs(username, password, save_pwd_var.get())
        
        # Cierra la ventana de login
        root.destroy()
        
        # Iniciar la aplicación
        start_app()
    except Exception as e:
        btn_login.config(state=tk.NORMAL)
        # Importante atrapar el error real y mostrarlo limpio
        error_msg = getattr(e, 'message', str(e))
        messagebox.showerror("Error de Autenticación", f"Credenciales inválidas o error de conexión:\n{error_msg}")

def start_app():
    try:
        import uvicorn
        from main import app
        import webview

        def run_server():
            try:
                uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")
            except Exception as e:
                with open("error_server.log", "w") as f:
                    f.write(str(e))

        t = threading.Thread(target=run_server, daemon=True)
        t.start()

        time.sleep(1.5)

        window = webview.create_window(
            'Microsip ERP - Calculadora Ecommerce',
            'http://127.0.0.1:8000',
            width=1280,
            height=800,
            resizable=True,
            maximized=True
        )
        webview.start()
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        messagebox.showerror("Error Interno", f"La aplicación falló al iniciar:\n{error_msg}")
        with open("error_fatal.log", "w") as f:
            f.write(error_msg)

if __name__ == '__main__':
    root = tk.Tk()
    root.title("Acceso a Microsip")
    
    # Cargar icono
    try:
        icon_path = os.path.join(sys._MEIPASS, 'app_icon.ico') if hasattr(sys, '_MEIPASS') else 'app_icon.ico'
        root.iconbitmap(icon_path)
    except Exception:
        pass

    root.geometry("350x300")
    root.resizable(False, False)
    root.eval('tk::PlaceWindow . center')

    tk.Label(root, text="ERP Microsip - Inicio de Sesión", font=("Segoe UI", 12, "bold")).pack(pady=15)
    
    tk.Label(root, text="Usuario Microsip:", font=("Segoe UI", 10)).pack()
    user_entry = tk.Entry(root, font=("Segoe UI", 10), width=30)
    user_entry.pack(pady=5)

    tk.Label(root, text="Contraseña:", font=("Segoe UI", 10)).pack()
    pass_entry = tk.Entry(root, show="*", font=("Segoe UI", 10), width=30)
    pass_entry.pack(pady=5)

    # Checkbox para guardar contraseña
    save_pwd_var = tk.BooleanVar()
    chk_save = tk.Checkbutton(root, text="Guardar contraseña", variable=save_pwd_var, font=("Segoe UI", 9))
    chk_save.pack(pady=5)

    # Cargar preferencias
    prefs = load_prefs()
    if prefs.get("username"):
        user_entry.insert(0, prefs["username"])
    if prefs.get("save_pwd"):
        save_pwd_var.set(True)
        pwd = deobfuscate(prefs.get("password", ""))
        if pwd:
            pass_entry.insert(0, pwd)

    btn_login = tk.Button(root, text="Ingresar", font=("Segoe UI", 10, "bold"), bg="#0d6efd", fg="white", command=login, width=20)
    btn_login.pack(pady=15)

    root.bind('<Return>', lambda event: login())
    root.mainloop()
