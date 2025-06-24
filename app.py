import datetime
import time
import random
import math
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here_ganti_dengan_kuat'
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=120, ping_interval=25)

# --- Konfigurasi Sistem ---
SUHU_UDARA_PANAS_THRESHOLD = 32.0 # Jika suhu udara simulasi di atas ini, untuk informasi suhu
INTERVAL_SIMULASI = 20 # Interval simulasi dalam detik (1 menit)

# Probabilitas malfungsi (dalam persen)
PROB_ATAP_MACET = 0.01 # 1% kemungkinan atap macet
PROB_SENSOR_SUHU_RUSAK = 0.005 # 0.5% kemungkinan sensor suhu udara rusak
PROB_SENSOR_CAHAYA_RUSAK = 0.005 # 0.5% kemungkinan sensor cahaya rusak

# Konfigurasi simulasi cuaca (state machine)
WEATHER_STATES = ["Cerah", "Hujan Ringan", "Hujan Sedang", "Hujan Deras"]
WEATHER_TRANSITIONS = {
    "Cerah": {"Hujan Ringan": 0.1, "Cerah": 0.9}, # 10% chance to start raining lightly
    "Hujan Ringan": {"Hujan Sedang": 0.1, "Cerah": 0.2, "Hujan Ringan": 0.7},
    "Hujan Sedang": {"Hujan Deras": 0.1, "Hujan Ringan": 0.2, "Hujan Sedang": 0.7},
    "Hujan Deras": {"Hujan Sedang": 0.3, "Hujan Deras": 0.7}
}

# --- Status Global Sistem ---
# Status atap: state, color_class, icon, detail_message
status_atap = {"state": "Tertutup", "color": "gray", "icon": "fa-cloud", "detail": "Sistem baru dimulai"}
suhu_udara_terbaru = 28.0
# Intensitas cahaya: state, color_class, icon
intensitas_cahaya = {"state": "Malam Hari", "color": "gray", "icon": "fa-moon"}
# Hujan: state, color_class, icon
is_hujan_terbaru = {"state": "Cerah", "color": "green", "icon": "fa-sun"}
current_weather_state = "Cerah" # Untuk simulasi durasi hujan/cerah

log_sistem = []

# Dummy Database untuk Data Historis
data_historis_suhu = []
data_historis_kejadian = []

# Waktu awal simulasi untuk tren suhu dan cahaya
start_time_of_simulation = time.time()
last_hujan_notification_state = "Cerah" # Untuk notifikasi hujan
last_atap_mode = "Otomatis" # "Otomatis" atau "Manual"

# Variabel untuk Dry Time
total_dry_time_seconds = 0
last_dry_check_time = time.time()

def tambah_log(pesan, level="INFO"):
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    log_entry = f"[{timestamp}] [{level}] {pesan}"
    log_sistem.append(log_entry)
    if len(log_sistem) > 50:
        log_sistem.pop(0)
    print(log_entry)
    socketio.emit('update_log', log_entry, namespace='/')

def tambah_data_historis_kejadian(event_desc):
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    data_historis_kejadian.append({'timestamp': timestamp, 'event': event_desc})
    if len(data_historis_kejadian) > 20:
        data_historis_kejadian.pop(0)

def format_duration(seconds):
    """Mengubah detik menjadi format HH:MM:SS"""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"

def simulate_system():
    global status_atap, suhu_udara_terbaru, intensitas_cahaya, is_hujan_terbaru, current_weather_state
    global start_time_of_simulation, last_hujan_notification_state, last_atap_mode
    global total_dry_time_seconds, last_dry_check_time

    tambah_log("Memulai simulasi sistem...", "SYSTEM")

    sensor_suhu_malfungsi = False
    sensor_cahaya_malfungsi = False
    atap_macet = False

    while True:
        current_time_dt = datetime.datetime.now()
        
        # --- Simulasi Sensor Suhu Udara ---
        if not sensor_suhu_malfungsi and random.random() * 100 < PROB_SENSOR_SUHU_RUSAK:
            sensor_suhu_malfungsi = True
            tambah_log("ERROR: Sensor suhu udara malfungsi! Membaca nilai tidak akurat.", "ERROR")
            tambah_data_historis_kejadian("Sensor Suhu Udara Malfungsi")

        if sensor_suhu_malfungsi:
            suhu_udara_terbaru = round(random.uniform(10.0, 40.0), 1)
            tambah_log(f"Sensor Suhu Udara (MALFUNGSI): {suhu_udara_terbaru}°C", "WARNING")
        else:
            sim_day_duration = 600 # 10 menit simulasi 1 hari
            time_in_day = (time.time() - start_time_of_simulation) % sim_day_duration
            
            t_norm = time_in_day / sim_day_duration
            base_temp_wave = -math.cos(2 * math.pi * (t_norm + 0.25))

            min_daily_temp_base = 25.0
            max_daily_temp_base = 35.0
            avg_temp_base = (min_daily_temp_base + max_daily_temp_base) / 2
            amplitude_base = (max_daily_temp_base - min_daily_temp_base) / 2

            simulated_base_temp = avg_temp_base + amplitude_base * base_temp_wave
            suhu_udara_terbaru = round(simulated_base_temp + random.uniform(-1.5, 1.5), 1)
            tambah_log(f"Sensor Suhu Udara: {suhu_udara_terbaru}°C")

        # --- Simulasi Sensor Cahaya (Siang/Malam + Malfungsi) ---
        if not sensor_cahaya_malfungsi and random.random() * 100 < PROB_SENSOR_CAHAYA_RUSAK:
            sensor_cahaya_malfungsi = True
            tambah_log("ERROR: Sensor cahaya malfungsi! Membaca nilai tidak akurat.", "ERROR")
            tambah_data_historis_kejadian("Sensor Cahaya Malfungsi")

        if sensor_cahaya_malfungsi:
            intensitas_cahaya = {"state": "Malfungsi", "color": "red", "icon": "fa-exclamation-triangle"}
            tambah_log("Sensor Cahaya (MALFUNGSI): Tidak dapat mendeteksi siang/malam.", "WARNING")
        else:
            if t_norm > 0.25 and t_norm < 0.75: # Ini adalah "siang" (25% - 75% dari siklus hari simulasi)
                intensitas_cahaya = {"state": "Siang Hari", "color": "yellow", "icon": "fa-sun"}
                tambah_log("Sensor Cahaya: Siang Hari.")
            else: # Ini adalah "malam"
                intensitas_cahaya = {"state": "Malam Hari", "color": "gray", "icon": "fa-moon"}
                tambah_log("Sensor Cahaya: Malam Hari.")


        # --- Simulasi Durasi Hujan/Cerah (State Machine) ---
        next_weather_state = current_weather_state
        rand_transition = random.random()
        cumulative_prob = 0
        for next_state, prob in WEATHER_TRANSITIONS[current_weather_state].items():
            cumulative_prob += prob
            if rand_transition < cumulative_prob:
                next_weather_state = next_state
                break
        
        # Perbarui is_hujan_terbaru berdasarkan next_weather_state
        if next_weather_state == "Cerah":
            is_hujan_terbaru = {"state": "Cerah", "color": "green", "icon": "fa-sun"}
        elif next_weather_state == "Hujan Ringan":
            is_hujan_terbaru = {"state": "Hujan Ringan", "color": "yellow", "icon": "fa-cloud-showers-heavy"}
        elif next_weather_state == "Hujan Sedang":
            is_hujan_terbaru = {"state": "Hujan Sedang", "color": "orange", "icon": "fa-cloud-rain"}
        elif next_weather_state == "Hujan Deras":
            is_hujan_terbaru = {"state": "Hujan Deras", "color": "red", "icon": "fa-cloud-bolt"}
        
        # Notifikasi Hujan (jika status berubah dari cerah ke hujan)
        if is_hujan_terbaru["state"] != "Cerah" and last_hujan_notification_state == "Cerah":
            socketio.emit('hujan_terdeteksi', is_hujan_terbaru["state"], namespace='/')
            tambah_log(f"NOTIFIKASI: Hujan mulai! ({is_hujan_terbaru['state']})", "WARNING")
            tambah_data_historis_kejadian(f"Hujan Mulai: {is_hujan_terbaru['state']}")
        elif is_hujan_terbaru["state"] == "Cerah" and last_hujan_notification_state != "Cerah":
            tambah_log("NOTIFIKASI: Hujan berhenti, cuaca cerah kembali.", "INFO")
            tambah_data_historis_kejadian("Hujan Berhenti (Cerah)")
        
        last_hujan_notification_state = is_hujan_terbaru["state"] # Simpan status hujan saat ini untuk perbandingan di iterasi berikutnya
        current_weather_state = next_weather_state # Perbarui state cuaca untuk iterasi berikutnya


        # --- Logika Kontrol Penutup Atap Otomatis (dengan Manual Override) ---
        # Prioritas: Malfungsi atap > Hujan > Malam/Gelap > Siang/Cerah
        
        new_atap_state = status_atap["state"] # Simpan state atap saat ini untuk deteksi perubahan

        if last_atap_mode == "Otomatis": # Hanya jalankan logika otomatis jika mode tidak di-override manual
            if atap_macet:
                status_atap = {"state": "Malfungsi", "color": "red", "icon": "fa-times-circle", "detail": "Atap macet, tidak dapat dikendalikan."}
                tambah_log("Atap dalam kondisi malfungsi, tidak dapat dikendalikan.", "ERROR")
            elif is_hujan_terbaru["state"] != "Cerah": # Jika hujan (apapun intensitasnya)
                if status_atap["state"] != "Tertutup":
                    status_atap = {"state": "Menutup", "color": "orange", "icon": "fa-cog", "detail": f"Menutup otomatis karena {is_hujan_terbaru['state']}."}
                    tambah_log(f"Atap menutup otomatis karena terdeteksi {is_hujan_terbaru['state']}.")
                    tambah_data_historis_kejadian(f"Atap Menutup Otomatis (Hujan)")
                    time.sleep(0.5) # Simulasi delay untuk visualisasi
                    status_atap = {"state": "Tertutup", "color": "red", "icon": "fa-cloud-rain", "detail": f"Tertutup otomatis karena {is_hujan_terbaru['state']}."}
                else:
                    status_atap = {"state": "Tertutup", "color": "red", "icon": "fa-cloud-rain", "detail": f"Sudah tertutup karena {is_hujan_terbaru['state']}."}
                    tambah_log("Atap sudah tertutup karena hujan.")
            elif intensitas_cahaya["state"] == "Malam Hari" or sensor_cahaya_malfungsi:
                if status_atap["state"] != "Tertutup":
                    status_atap = {"state": "Menutup", "color": "orange", "icon": "fa-cog", "detail": "Menutup otomatis karena hari sudah gelap."}
                    tambah_log("Atap menutup otomatis karena hari sudah gelap.")
                    tambah_data_historis_kejadian("Atap Menutup Otomatis (Malam)")
                    time.sleep(0.5)
                    status_atap = {"state": "Tertutup", "color": "gray", "icon": "fa-moon", "detail": "Tertutup otomatis karena hari sudah gelap."}
                else:
                    status_atap = {"state": "Tertutup", "color": "gray", "icon": "fa-moon", "detail": "Sudah tertutup karena hari sudah gelap."}
                    tambah_log("Atap sudah tertutup karena hari sudah gelap.")
            else: # Siang hari dan tidak hujan
                if status_atap["state"] != "Terbuka":
                    status_atap = {"state": "Membuka", "color": "orange", "icon": "fa-cog", "detail": "Membuka otomatis karena siang hari dan cuaca cerah."}
                    tambah_log("Atap membuka otomatis karena siang hari dan cuaca cerah.")
                    tambah_data_historis_kejadian("Atap Membuka Otomatis (Siang/Cerah)")
                    time.sleep(0.5)
                    status_atap = {"state": "Terbuka", "color": "green", "icon": "fa-sun", "detail": "Terbuka otomatis untuk penjemuran."}
                else:
                    status_atap = {"state": "Terbuka", "color": "green", "icon": "fa-sun", "detail": "Sudah terbuka untuk penjemuran."}
                    tambah_log("Atap sudah terbuka.")
        
        # --- Logika Dry Time ---
        current_time_for_dry_check = time.time()
        time_diff = current_time_for_dry_check - last_dry_check_time

        # Tambahkan dry time hanya jika penutup terbuka, siang hari, dan tidak hujan
        if status_atap["state"] == "Terbuka" and intensitas_cahaya["state"] == "Siang Hari" and is_hujan_terbaru["state"] == "Cerah" and last_atap_mode == "Otomatis":
            total_dry_time_seconds += time_diff
            tambah_log(f"Dry Time aktif. Total: {format_duration(total_dry_time_seconds)}", "INFO")
        last_dry_check_time = current_time_for_dry_check


        # --- Manajemen Data Historis Suhu Udara ---
        data_historis_suhu.append({
            'timestamp': current_time_dt.strftime('%H:%M:%S'),
            'suhu': suhu_udara_terbaru
        })
        if len(data_historis_suhu) > 60: # Simpan 60 data suhu terakhir (1 jam data @ 1m interval)
            data_historis_suhu.pop(0)

        # --- Kirim Data ke Klien Web ---
        data_to_send = {
            'suhu_udara': suhu_udara_terbaru,
            'intensitas_cahaya': intensitas_cahaya,
            'is_hujan': is_hujan_terbaru,
            'status_atap': status_atap, # Mengandung detail message
            'last_update': current_time_dt.strftime('%H:%M:%S'),
            'data_historis_suhu': data_historis_suhu,
            'data_historis_kejadian': data_historis_kejadian,
            'total_dry_time': format_duration(total_dry_time_seconds), # Kirim dry time
            'current_mode': last_atap_mode # Kirim mode atap
        }
        socketio.emit('update_data', data_to_send, namespace='/')

        time.sleep(INTERVAL_SIMULASI)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def test_connect():
    tambah_log('Klien terhubung', "CLIENT")
    initial_data = {
        'suhu_udara': suhu_udara_terbaru,
        'intensitas_cahaya': intensitas_cahaya,
        'is_hujan': is_hujan_terbaru,
        'status_atap': status_atap,
        'last_update': datetime.datetime.now().strftime('%H:%M:%S'),
        'data_historis_suhu': data_historis_suhu,
        'data_historis_kejadian': data_historis_kejadian,
        'total_dry_time': format_duration(total_dry_time_seconds),
        'current_mode': last_atap_mode
    }
    emit('update_data', initial_data, namespace='/')
    for log_entry in log_sistem:
        emit('update_log', log_entry, namespace='/')

@socketio.on('disconnect')
def test_disconnect():
    tambah_log('Klien terputus', "CLIENT")

# --- Event Handler untuk Tombol Manual Atap ---
@socketio.on('atur_atap_manual')
def handle_atur_atap_manual(aksi): # aksi bisa "buka" atau "tutup"
    global status_atap, last_atap_mode
    tambah_log(f"Perintah manual: Mengatur atap ke '{aksi}'.", "USER")
    
    last_atap_mode = "Manual" # Set mode ke manual

    if aksi == "buka":
        status_atap = {"state": "Terbuka", "color": "green", "icon": "fa-hand-pointer", "detail": "Dibuka secara manual oleh operator."}
    elif aksi == "tutup":
        status_atap = {"state": "Tertutup", "color": "red", "icon": "fa-hand-pointer", "detail": "Ditutup secara manual oleh operator."}
    
    emit('update_data', {'status_atap': status_atap, 'current_mode': last_atap_mode}, namespace='/') # Kirim update segera
    tambah_data_historis_kejadian(f"Atap Diatur Manual: {aksi.capitalize()}")

@socketio.on('reset_mode_otomatis')
def handle_reset_mode_otomatis():
    global last_atap_mode, status_atap
    tambah_log("Perintah manual: Mengembalikan mode atap ke Otomatis.", "USER")
    last_atap_mode = "Otomatis"
    # Atap akan mengikuti logika otomatis pada siklus berikutnya
    emit('update_data', {'current_mode': last_atap_mode}, namespace='/')
    tambah_data_historis_kejadian("Mode Atap Kembali Otomatis")


if __name__ == '__main__':
    start_time_of_simulation = time.time()
    last_dry_check_time = time.time() # Inisialisasi di sini juga
    simulation_thread = threading.Thread(target=simulate_system)
    simulation_thread.daemon = True
    simulation_thread.start()
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)