# app.py
import sqlite3
from datetime import datetime
import base64
import os
import pandas as pd
from pathlib import Path
import json
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

# ========== Flask приложение ==========
app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'

# ========== База данных SQLite ==========
def init_db():
    """Инициализация базы данных с таблицами для системы учета заявок"""
    db_path = 'service_requests.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Проверяем существование таблицы users
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if cursor.fetchone() is None:
        create_tables_from_scratch(conn, cursor)
    else:
        print(f"База данных {db_path} уже существует, используем существующие таблицы")
        # Проверяем и исправляем структуру таблиц при необходимости
        check_and_update_tables(conn, cursor)
        
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        if user_count == 0:
            load_users_from_xlsx(conn, cursor)
    
    conn.commit()
    conn.close()

def check_and_update_tables(conn, cursor):
    """Проверка и обновление структуры таблиц"""
    print("Проверка структуры таблиц...")
    
    # Проверяем структуру таблицы comments
    cursor.execute("PRAGMA table_info(comments)")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]
    
    # Проверяем наличие необходимых столбцов
    required_columns = ['id', 'request_id', 'user_id', 'user_fio', 'user_type', 'message', 'created_at']
    missing_columns = []
    
    for col in required_columns:
        if col not in column_names:
            missing_columns.append(col)
    
    if missing_columns:
        print(f"В таблице comments отсутствуют столбцы: {missing_columns}")
        print("Исправляем структуру таблицы comments...")
        
        # Создаем временную таблицу с правильной структурой
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS comments_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id INTEGER,
            request_id INTEGER NOT NULL,
            master_id INTEGER,
            user_id INTEGER,
            user_fio TEXT,
            user_type TEXT,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (request_id) REFERENCES service_requests(request_id),
            FOREIGN KEY (master_id) REFERENCES masters(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        ''')
        
        # Копируем данные из старой таблицы в новую
        try:
            # Получаем список столбцов из старой таблицы
            cursor.execute("PRAGMA table_info(comments)")
            old_columns = cursor.fetchall()
            old_column_names = [col[1] for col in old_columns]
            
            # Строим запрос для копирования данных
            select_columns = []
            insert_columns = []
            
            for col in old_column_names:
                if col in ['id', 'comment_id', 'request_id', 'master_id', 'message', 'created_at']:
                    select_columns.append(col)
                    insert_columns.append(col)
                elif col.lower() == 'user_id' or col == 'User_id':
                    select_columns.append(col)
                    insert_columns.append('user_id')
                elif col.lower() == 'user_fio' or col == 'user_fio':
                    select_columns.append(col)
                    insert_columns.append('user_fio')
                elif col.lower() == 'user_type' or col == 'user_type':
                    select_columns.append(col)
                    insert_columns.append('user_type')
            
            # Добавляем недостающие столбцы с NULL значениями
            for col in ['user_id', 'user_fio', 'user_type']:
                if col not in insert_columns:
                    select_columns.append('NULL')
                    insert_columns.append(col)
            
            # Копируем данные
            select_sql = f"SELECT {', '.join(select_columns)} FROM comments"
            cursor.execute(select_sql)
            rows = cursor.fetchall()
            
            if rows:
                insert_sql = f"INSERT INTO comments_new ({', '.join(insert_columns)}) VALUES ({', '.join(['?'] * len(insert_columns))})"
                cursor.executemany(insert_sql, rows)
            
            # Удаляем старую таблицу и переименовываем новую
            cursor.execute("DROP TABLE comments")
            cursor.execute("ALTER TABLE comments_new RENAME TO comments")
            print("Структура таблицы comments успешно обновлена")
            
        except Exception as e:
            print(f"Ошибка при обновлении таблицы comments: {e}")
            # Если не удалось скопировать данные, оставляем новую таблицу пустой
            cursor.execute("DROP TABLE IF EXISTS comments_new")
            print("Создана новая таблица comments с правильной структурой")
    
    else:
        print("Таблица comments имеет правильную структуру")
    
    # Проверяем наличие таблицы masters
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='masters'")
    if cursor.fetchone() is None:
        print("Создаем таблицу masters...")
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS masters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            master_fio TEXT NOT NULL,
            master_phone TEXT,
            master_login TEXT UNIQUE,
            master_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        ''')
    
    # Проверяем наличие таблицы status_history
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='status_history'")
    if cursor.fetchone() is None:
        print("Создаем таблицу status_history...")
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            changed_by TEXT NOT NULL,
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            comment TEXT,
            FOREIGN KEY (request_id) REFERENCES service_requests(request_id)
        )
        ''')

def create_tables_from_scratch(conn, cursor):
    """Создание всех таблиц с нуля на основе данных из xlsx"""
    print("Создание таблиц базы данных с нуля...")
    
    # Удаляем старые таблицы, если они есть
    cursor.execute("DROP TABLE IF EXISTS comments")
    cursor.execute("DROP TABLE IF EXISTS service_requests")
    cursor.execute("DROP TABLE IF EXISTS masters")
    cursor.execute("DROP TABLE IF EXISTS users")
    cursor.execute("DROP TABLE IF EXISTS status_history")
    
    # Создаем таблицу пользователей (для аутентификации)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        login TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        fio TEXT NOT NULL,
        phone TEXT,
        user_type TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Создаем таблицу мастеров (специалистов)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS masters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        master_fio TEXT NOT NULL,
        master_phone TEXT,
        master_login TEXT UNIQUE,
        master_type TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')
    
    # Создаем таблицу комментариев
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        comment_id INTEGER,
        request_id INTEGER NOT NULL,
        master_id INTEGER,
        user_id INTEGER,
        user_fio TEXT,
        user_type TEXT,
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (request_id) REFERENCES service_requests(request_id),
        FOREIGN KEY (master_id) REFERENCES masters(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')
    
    # Создаем таблицу заявок
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS service_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER UNIQUE NOT NULL,
        start_date TIMESTAMP NOT NULL,
        tech_type TEXT NOT NULL,
        tech_model TEXT NOT NULL,
        problem_description TEXT NOT NULL,
        request_status TEXT NOT NULL,
        completion_date TIMESTAMP,
        days_in_process INTEGER,
        repair_parts TEXT,
        has_comment BOOLEAN DEFAULT FALSE,
        master_id INTEGER,
        master_fio TEXT,
        master_phone TEXT,
        master_login TEXT,
        master_type TEXT,
        client_id INTEGER,
        client_fio TEXT NOT NULL,
        client_phone TEXT NOT NULL,
        client_login TEXT,
        client_type TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (master_id) REFERENCES masters(id),
        FOREIGN KEY (client_id) REFERENCES users(id)
    )
    ''')
    
    # Создаем таблицу истории изменения статусов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL,
        old_status TEXT,
        new_status TEXT NOT NULL,
        changed_by TEXT NOT NULL,
        changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        comment TEXT,
        FOREIGN KEY (request_id) REFERENCES service_requests(request_id)
    )
    ''')
    
    # Загружаем данные из всех файлов
    load_all_data(conn, cursor)
    
    print("Таблицы успешно созданы и данные загружены")

def load_all_data(conn, cursor):
    """Загрузка данных из всех Excel файлов"""
    # 1. Сначала загружаем пользователей
    load_users_from_xlsx(conn, cursor)
    
    # 2. Загружаем заявки
    load_requests_from_xlsx(conn, cursor)
    
    # 3. Загружаем комментарии
    load_comments_from_xlsx(conn, cursor)

def load_users_from_xlsx(conn, cursor):
    """Загрузка данных пользователей из Excel файла"""
    try:
        users_file_path = 'inputDataUsers.xlsx'
        if not os.path.exists(users_file_path):
            print(f"Файл {users_file_path} не найден!")
            create_default_users(conn, cursor)
            return
            
        df = pd.read_excel(users_file_path, sheet_name='Sheet1')
        print(f"Загружено {len(df)} записей из Excel файла пользователей")
        
        # Тип пользователя для соответствия с нашей системой
        type_mapping = {
            'Менеджер': 'admin',
            'Мастер': 'master',
            'Оператор': 'operator',
            'Заказчик': 'client'
        }
        
        for idx, row in df.iterrows():
            try:
                user_id = int(row['userID']) if pd.notna(row['userID']) else idx + 1
                user_type_excel = row['type'] if pd.notna(row['type']) else 'Заказчик'
                user_type = type_mapping.get(user_type_excel, 'client')
                
                password = str(row['password']) if pd.notna(row['password']) else 'password123'
                password_hash = generate_password_hash(password)
                
                # Добавляем пользователя
                cursor.execute('''
                INSERT OR REPLACE INTO users (id, login, password_hash, fio, phone, user_type)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    user_id,
                    row['login'] if pd.notna(row['login']) else f'user{idx+1}',
                    password_hash,
                    row['fio'] if pd.notna(row['fio']) else f'Пользователь {idx+1}',
                    str(row['phone']) if pd.notna(row['phone']) else '',
                    user_type
                ))
                
                # Если пользователь является специалистом, добавляем его в таблицу мастеров
                if user_type == 'master':
                    cursor.execute('''
                    INSERT OR REPLACE INTO masters (user_id, master_fio, master_phone, master_login, master_type)
                    VALUES (?, ?, ?, ?, ?)
                    ''', (
                        user_id,
                        row['fio'] if pd.notna(row['fio']) else f'Пользователь {idx+1}',
                        str(row['phone']) if pd.notna(row['phone']) else '',
                        row['login'] if pd.notna(row['login']) else f'user{idx+1}',
                        'Мастер'
                    ))
                
                print(f"Добавлен пользователь: {row['login']} ({user_type})")
                
            except Exception as e:
                print(f"Ошибка при обработке пользователя {idx}: {e}")
        
        print(f"Загружено {len(df)} пользователей в базу данных")
        
    except Exception as e:
        print(f"Ошибка при загрузке пользователей из Excel: {e}")
        create_default_users(conn, cursor)

def load_requests_from_xlsx(conn, cursor):
    """Загрузка данных заявок из Excel файла"""
    try:
        # Используем данные из service_requests_combined.xlsx или inputDataRequests.xlsx
        requests_file_path = 'service_requests_combined.xlsx'
        if not os.path.exists(requests_file_path):
            requests_file_path = 'inputDataRequests.xlsx'
            
        if not os.path.exists(requests_file_path):
            print(f"Файл заявок не найден!")
            return
            
        df = pd.read_excel(requests_file_path, sheet_name='Sheet1')
        print(f"Загружено {len(df)} записей из Excel файла заявок")
        
        for idx, row in df.iterrows():
            try:
                # Для service_requests_combined.xlsx
                if 'client_id' in df.columns:
                    client_id = int(row['client_id']) if pd.notna(row['client_id']) else None
                    master_id = int(row['master_id']) if pd.notna(row['master_id']) else None
                    
                    # Получаем данные клиента
                    cursor.execute("SELECT fio, phone, login, user_type FROM users WHERE id = ?", (client_id,))
                    client_data = cursor.fetchone()
                    
                    # Получаем данные мастера
                    master_fio = row['master_fio'] if pd.notna(row['master_fio']) else ''
                    master_phone = str(row['master_phone']) if pd.notna(row['master_phone']) else ''
                    master_login = row['master_login'] if pd.notna(row['master_login']) else ''
                    
                    cursor.execute('''
                    INSERT OR REPLACE INTO service_requests (
                        request_id, start_date, tech_type, tech_model, problem_description,
                        request_status, completion_date, days_in_process, repair_parts,
                        has_comment, master_id, master_fio, master_phone, master_login, master_type,
                        client_id, client_fio, client_phone, client_login, client_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        int(row['request_id']) if pd.notna(row['request_id']) else idx + 1,
                        row['start_date'] if pd.notna(row['start_date']) else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        row['tech_type'] if pd.notna(row['tech_type']) else '',
                        row['tech_model'] if pd.notna(row['tech_model']) else '',
                        row['problem_description'] if pd.notna(row['problem_description']) else '',
                        row['request_status'] if pd.notna(row['request_status']) else 'Новая заявка',
                        row['completion_date'] if pd.notna(row['completion_date']) else None,
                        int(row['days_in_process']) if pd.notna(row['days_in_process']) else 0,
                        row['repair_parts'] if pd.notna(row['repair_parts']) else '',
                        bool(row['has_comment']) if pd.notna(row['has_comment']) else False,
                        master_id,
                        master_fio,
                        master_phone,
                        master_login,
                        'Мастер' if master_id else '',
                        client_id,
                        row['client_fio'] if pd.notna(row['client_fio']) else 'Неизвестный клиент',
                        str(row['client_phone']) if pd.notna(row['client_phone']) else '',
                        row['client_login'] if pd.notna(row['client_login']) else '',
                        row['client_type'] if pd.notna(row['client_type']) else 'client'
                    ))
                else:
                    # Для inputDataRequests.xlsx
                    client_id = int(row['clientID']) if pd.notna(row['clientID']) else None
                    master_id = int(row['masterID']) if pd.notna(row['masterID']) else None
                    
                    # Получаем данные клиента
                    cursor.execute("SELECT fio, phone, login, user_type FROM users WHERE id = ?", (client_id,))
                    client_data = cursor.fetchone()
                    
                    # Получаем данные мастера
                    master_data = None
                    if master_id:
                        cursor.execute("SELECT master_fio, master_phone, master_login FROM masters WHERE id = ?", (master_id,))
                        master_data = cursor.fetchone()
                    
                    # Обработка дат
                    start_date = row['startDate']
                    if isinstance(start_date, pd.Timestamp):
                        start_date = start_date.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        start_date = str(start_date) if pd.notna(start_date) else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
                    completion_date = row['completionDate']
                    if pd.notna(completion_date):
                        if isinstance(completion_date, pd.Timestamp):
                            completion_date = completion_date.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            completion_date = str(completion_date)
                    else:
                        completion_date = None
                    
                    # Расчет days_in_process
                    days_in_process = None
                    if completion_date:
                        try:
                            start_dt = datetime.strptime(start_date[:10], '%Y-%m-%d')
                            end_dt = datetime.strptime(completion_date[:10], '%Y-%m-%d')
                            days_in_process = (end_dt - start_dt).days
                        except:
                            days_in_process = 0
                    
                    # Добавляем заявку
                    cursor.execute('''
                    INSERT OR REPLACE INTO service_requests (
                        request_id, start_date, tech_type, tech_model, problem_description,
                        request_status, completion_date, days_in_process, repair_parts,
                        master_id, master_fio, master_phone, master_login, master_type,
                        client_id, client_fio, client_phone, client_login, client_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        int(row['requestID']),
                        start_date,
                        row['homeTechType'] if pd.notna(row['homeTechType']) else '',
                        row['homeTechModel'] if pd.notna(row['homeTechModel']) else '',
                        row['problemDescryption'] if pd.notna(row['problemDescryption']) else '',
                        row['requestStatus'] if pd.notna(row['requestStatus']) else 'Новая заявка',
                        completion_date,
                        days_in_process,
                        row['repairParts'] if pd.notna(row['repairParts']) else '',
                        master_id,
                        master_data[0] if master_data else '',
                        master_data[1] if master_data else '',
                        master_data[2] if master_data else '',
                        'Мастер' if master_data else '',
                        client_id,
                        client_data[0] if client_data else 'Неизвестный клиент',
                        client_data[1] if client_data else '',
                        client_data[2] if client_data else '',
                        client_data[3] if client_data else 'client'
                    ))
                
            except Exception as e:
                print(f"Ошибка при обработке заявки {idx}: {e}")
        
        print(f"Загружено {len(df)} заявок в базу данных")
        
    except Exception as e:
        print(f"Ошибка при загрузке заявок из Excel: {e}")

def load_comments_from_xlsx(conn, cursor):
    """Загрузка комментариев из Excel файла"""
    try:
        comments_file_path = 'inputDataComments.xlsx'
        if not os.path.exists(comments_file_path):
            print(f"Файл {comments_file_path} не найден!")
            return
            
        df = pd.read_excel(comments_file_path, sheet_name='Sheet1')
        print(f"Загружено {len(df)} записей из Excel файла комментариев")
        
        # Получаем словарь masterID -> user_id
        cursor.execute("SELECT id, user_id, master_fio FROM masters")
        masters_data = cursor.fetchall()
        master_id_to_user_id = {}
        master_id_to_fio = {}
        
        for master_row in masters_data:
            master_id_to_user_id[master_row[0]] = master_row[1]
            master_id_to_fio[master_row[0]] = master_row[2]
        
        # Получаем словарь user_id -> user_type
        cursor.execute("SELECT id, user_type FROM users")
        users_data = cursor.fetchall()
        user_id_to_type = {row[0]: row[1] for row in users_data}
        
        for idx, row in df.iterrows():
            try:
                comment_id = int(row['commentID']) if pd.notna(row['commentID']) else None
                request_id = int(row['requestID']) if pd.notna(row['requestID']) else None
                master_id = int(row['masterID']) if pd.notna(row['masterID']) else None
                
                # Получаем user_id и данные пользователя для комментария
                user_id = None
                user_fio = None
                user_type = None
                
                if master_id in master_id_to_user_id:
                    user_id = master_id_to_user_id[master_id]
                    user_fio = master_id_to_fio.get(master_id, 'Неизвестный мастер')
                    user_type = user_id_to_type.get(user_id, 'master')
                
                # Добавляем комментарий
                cursor.execute('''
                INSERT OR REPLACE INTO comments (comment_id, request_id, master_id, user_id, user_fio, user_type, message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    comment_id,
                    request_id,
                    master_id,
                    user_id,
                    user_fio,
                    user_type,
                    row['message'] if pd.notna(row['message']) else ''
                ))
                
                # Обновляем флаг has_comment в заявке
                if request_id:
                    cursor.execute('''
                    UPDATE service_requests 
                    SET has_comment = 1 
                    WHERE request_id = ?
                    ''', (request_id,))
                
                print(f"Добавлен комментарий {comment_id} для заявки {request_id} от мастера {master_id}")
                
            except Exception as e:
                print(f"Ошибка при обработке комментария {idx}: {e}")
        
        print(f"Загружено {len(df)} комментариев в базу данных")
        
    except Exception as e:
        print(f"Ошибка при загрузке комментариев из Excel: {e}")

def create_default_users(conn, cursor):
    """Создание пользователей по умолчанию"""
    default_users = [
        ('admin', 'admin123', 'Администратор Системы', '88001234567', 'admin'),
        ('manager1', 'manager123', 'Менеджер 1', '89501112233', 'admin'),
        ('master1', 'master123', 'Мастер 1', '89502223344', 'master'),
        ('master2', 'master123', 'Мастер 2', '89503334455', 'master'),
        ('operator1', 'operator123', 'Оператор 1', '89504445566', 'operator'),
        ('client1', 'client123', 'Клиент 1', '89151234567', 'client'),
        ('client2', 'client123', 'Клиент 2', '89152345678', 'client'),
    ]
    
    for login, password, fio, phone, user_type in default_users:
        password_hash = generate_password_hash(password)
        cursor.execute('''
        INSERT OR IGNORE INTO users (login, password_hash, fio, phone, user_type)
        VALUES (?, ?, ?, ?, ?)
        ''', (login, password_hash, fio, phone, user_type))
        
        if user_type == 'master':
            # Получаем user_id
            cursor.execute("SELECT id FROM users WHERE login = ?", (login,))
            user_row = cursor.fetchone()
            if user_row:
                user_id = user_row[0]
                cursor.execute('''
                INSERT OR IGNORE INTO masters (user_id, master_fio, master_phone, master_login, master_type)
                VALUES (?, ?, ?, ?, ?)
                ''', (user_id, fio, phone, login, 'Мастер'))
    
    print("Пользователи по умолчанию созданы")

# Инициализация БД
init_db()

# Функция для создания логотипа (остается без изменений)
def create_logo():
    try:
        with open('logo.png', 'rb') as f:
            logo_data = f.read()
            logo_base64 = base64.b64encode(logo_data).decode('utf-8')
            return "data:image/png;base64," + logo_base64
    except FileNotFoundError:
        print("Файл logo.png не найден, используется SVG логотип")
        svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="200" height="60" viewBox="0 0 200 60" xmlns="http://www.w3.org/2000/svg">
    <defs>
        <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" style="stop-color:#667eea;stop-opacity:1" />
            <stop offset="100%" style="stop-color:#764ba2;stop-opacity:1" />
        </linearGradient>
        <linearGradient id="grad2" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" style="stop-color:#4facfe;stop-opacity:1" />
            <stop offset="100%" style="stop-color:#00f2fe;stop-opacity:1" />
        </linearGradient>
    </defs>
    <rect width="200" height="60" rx="12" fill="url(#grad1)"/>
    <rect x="15" y="10" width="40" height="40" rx="8" fill="url(#grad2)"/>
    <path d="M25,25 L45,25 M25,30 L45,30 M25,35 L45,35" stroke="white" stroke-width="2" stroke-linecap="round"/>
    <text x="65" y="28" font-family="Arial, sans-serif" font-size="14" font-weight="bold" fill="white">SERVICE</text>
    <text x="65" y="42" font-family="Arial, sans-serif" font-size="12" fill="rgba(255,255,255,0.8)">CENTER</text>
</svg>'''
        
        logo_base64 = "data:image/svg+xml;base64," + base64.b64encode(svg_content.encode('utf-8')).decode('utf-8')
        return logo_base64

logo_base64 = create_logo()

# ========== Маршруты Flask ==========

@app.route('/', methods=['GET', 'POST'])
def index():
    """Главная страница с аутентификацией"""
    if 'user_id' in session:
        return render_main_page()
    elif request.method == 'POST':
        return handle_login_form()
    else:
        return render_login_page()

def handle_login_form():
    """Обработка данных входа из формы"""
    login = request.form.get('login')
    password = request.form.get('password')
    
    if not login or not password:
        return render_login_page(error="Введите логин и пароль")
    
    try:
        conn = sqlite3.connect('service_requests.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE login = ?", (login,))
        user = cursor.fetchone()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['user_login'] = user['login']
            session['user_name'] = user['fio']
            session['user_type'] = user['user_type']
            
            conn.close()
            return render_main_page()
        else:
            conn.close()
            return render_login_page(error="Неверный логин или пароль")
            
    except Exception as e:
        return render_login_page(error=f"Ошибка сервера: {str(e)}")

def render_login_page(error=None):
    """Рендеринг страницы входа с реальными паролями"""
    error_html = f'''
    <div style="background-color: #fee; color: #c00; padding: 10px; border-radius: 5px; margin-bottom: 20px; text-align: center;">
        {error}
    </div>
    ''' if error else ''
    
    # Получаем список всех пользователей с реальными паролями из файла
    try:
        users_file_path = 'inputDataUsers.xlsx'
        if os.path.exists(users_file_path):
            df = pd.read_excel(users_file_path, sheet_name='Sheet1')
            users_html = ""
            for idx, row in df.iterrows():
                login = row['login'] if pd.notna(row['login']) else f'user{idx+1}'
                password = str(row['password']) if pd.notna(row['password']) else 'password123'
                fio = row['fio'] if pd.notna(row['fio']) else f'Пользователь {idx+1}'
                user_type_excel = row['type'] if pd.notna(row['type']) else 'Заказчик'
                
                users_html += f'''
                <div class="account-item">
                    <strong>{fio} ({user_type_excel}):</strong> {login} / <span style="color: #4f46e5; font-weight: bold;">{password}</span>
                </div>
                '''
        else:
            # Если файл не найден, используем данные по умолчанию
            users_html = '''
            <div class="account-item"><strong>Администратор:</strong> admin / <span style="color: #4f46e5; font-weight: bold;">admin123</span></div>
            <div class="account-item"><strong>Менеджер:</strong> kasoo / <span style="color: #4f46e5; font-weight: bold;">root</span></div>
            <div class="account-item"><strong>Мастер:</strong> murashov123 / <span style="color: #4f46e5; font-weight: bold;">qwerty</span></div>
            <div class="account-item"><strong>Оператор:</strong> perinaAD / <span style="color: #4f46e5; font-weight: bold;">250519</span></div>
            <div class="account-item"><strong>Мастер:</strong> test1 / <span style="color: #4f46e5; font-weight: bold;">test1</span></div>
            <div class="account-item"><strong>Заказчик:</strong> login2 / <span style="color: #4f46e5; font-weight: bold;">pass2</span></div>
            <div class="account-item"><strong>Заказчик:</strong> login3 / <span style="color: #4f46e5; font-weight: bold;">pass3</span></div>
            <div class="account-item"><strong>Заказчик:</strong> login4 / <span style="color: #4f46e5; font-weight: bold;">pass4</span></div>
            <div class="account-item"><strong>Мастер:</strong> login5 / <span style="color: #4f46e5; font-weight: bold;">pass5</span></div>
            '''
    except Exception as e:
        print(f"Ошибка при чтении файла пользователей: {e}")
        users_html = '''
        <div class="account-item"><strong>Администратор:</strong> admin / admin123</div>
        <div class="account-item"><strong>Менеджер:</strong> kasoo / root</div>
        <div class="account-item"><strong>Мастер:</strong> murashov123 / qwerty</div>
        <div class="account-item"><strong>Оператор:</strong> perinaAD / 250519</div>
        '''
    
    login_html = f'''
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Вход - Сервисный центр</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            :root {{
                --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                --secondary-gradient: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
                --accent-color: #4f46e5;
                --bg-primary: #f8fafc;
                --text-primary: #1e293b;
                --text-secondary: #64748b;
                --shadow-lg: 0 20px 25px -5px rgba(0,0,0,0.1);
            }}
            
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                background: var(--primary-gradient);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            
            .login-container {{
                width: 100%;
                max-width: 500px;
            }}
            
            .login-card {{
                background: white;
                border-radius: 20px;
                padding: 40px;
                box-shadow: var(--shadow-lg);
                text-align: center;
            }}
            
            .logo {{
                width: 80px;
                height: 80px;
                margin: 0 auto 20px;
                border-radius: 12px;
                background: var(--secondary-gradient);
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 36px;
            }}
            
            h1 {{
                color: var(--text-primary);
                margin-bottom: 10px;
                font-size: 28px;
            }}
            
            .subtitle {{
                color: var(--text-secondary);
                margin-bottom: 30px;
                font-size: 14px;
            }}
            
            .form-group {{
                margin-bottom: 20px;
                text-align: left;
            }}
            
            label {{
                display: block;
                margin-bottom: 8px;
                color: var(--text-primary);
                font-weight: 500;
            }}
            
            input {{
                width: 100%;
                padding: 14px 18px;
                border: 2px solid #e2e8f0;
                border-radius: 10px;
                font-size: 16px;
                transition: border-color 0.3s;
            }}
            
            input:focus {{
                outline: none;
                border-color: var(--accent-color);
            }}
            
            button {{
                width: 100%;
                padding: 14px;
                background: var(--primary-gradient);
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: transform 0.2s;
            }}
            
            button:hover {{
                transform: translateY(-2px);
            }}
            
            .test-accounts {{
                margin-top: 30px;
                padding: 20px;
                background: #f1f5f9;
                border-radius: 10px;
                text-align: left;
            }}
            
            .test-accounts h3 {{
                margin-bottom: 10px;
                font-size: 16px;
            }}
            
            .account-item {{
                margin-bottom: 8px;
                font-size: 14px;
                padding: 5px;
                border-bottom: 1px solid #e2e8f0;
                cursor: pointer;
                transition: background 0.2s;
            }}
            
            .account-item:hover {{
                background: #e2e8f0;
            }}
            
            .account-item:last-child {{
                border-bottom: none;
            }}
        </style>
    </head>
    <body>
        <div class="login-container">
            <div class="login-card">
                <div class="logo">
                    <i class="fas fa-tools"></i>
                </div>
                <h1>Сервисный центр "БытСервис"</h1>
                <p class="subtitle">Система учета заявок на ремонт бытовой техники</p>
                
                {error_html}
                
                <form method="POST" action="/">
                    <div class="form-group">
                        <label for="login">Логин</label>
                        <input type="text" id="login" name="login" required placeholder="Введите логин">
                    </div>
                    
                    <div class="form-group">
                        <label for="password">Пароль</label>
                        <input type="password" id="password" name="password" required placeholder="Введите пароль">
                    </div>
                    
                    <button type="submit">Войти</button>
                </form>
                
                <div class="test-accounts">
                    <h3>Тестовые учетные записи (из файла inputDataUsers.xlsx):</h3>
                    {users_html}
                    <div style="margin-top: 10px; font-size: 12px; color: #666; font-style: italic;">
                        Для входа используйте логин и пароль из списка выше
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            // Автозаполнение полей при клике на учетную запись
            document.querySelectorAll('.account-item').forEach(item => {{
                item.addEventListener('click', function() {{
                    const text = this.textContent;
                    const parts = text.split(':');
                    if (parts.length > 1) {{
                        const credentials = parts[1].trim().split('/');
                        if (credentials.length === 2) {{
                            const login = credentials[0].trim();
                            const password = credentials[1].trim();
                            
                            // Удаляем HTML теги из пароля если они есть
                            const cleanPassword = password.replace(/<[^>]*>/g, '').replace(/[^a-zA-Z0-9]/g, '');
                            
                            document.getElementById('login').value = login;
                            document.getElementById('password').value = cleanPassword;
                            
                            // Подсвечиваем поля
                            document.getElementById('login').style.borderColor = '#4f46e5';
                            document.getElementById('password').style.borderColor = '#4f46e5';
                            
                            setTimeout(() => {{
                                document.getElementById('login').style.borderColor = '';
                                document.getElementById('password').style.borderColor = '';
                            }}, 2000);
                        }}
                    }}
                }});
            }});
        </script>
    </body>
    </html>
    '''
    return login_html

def render_main_page():
    """Рендеринг главной страницы после входа"""
    user_type = session.get('user_type', 'client')
    user_name = session.get('user_name', 'Пользователь')
    
    user_type_names = {
        'admin': 'Администратор',
        'manager': 'Менеджер',
        'master': 'Мастер',
        'operator': 'Оператор',
        'client': 'Заказчик'
    }
    user_type_display = user_type_names.get(user_type, user_type)
    
    can_view_masters = user_type in ['admin', 'manager', 'master', 'operator']
    can_create_requests = user_type in ['admin', 'manager', 'client', 'operator']
    can_view_stats = user_type in ['admin', 'manager', 'operator']
    can_assign_masters = user_type in ['admin', 'manager', 'operator']
    can_edit_all = user_type in ['admin', 'manager', 'operator']
    can_edit_own = user_type == 'master'
    
    main_html = f'''
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Сервисный центр - Учет заявок</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            :root {{
                --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                --secondary-gradient: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
                --accent-color: #4f46e5;
                --bg-primary: #f8fafc;
                --bg-card: #ffffff;
                --text-primary: #1e293b;
                --text-secondary: #64748b;
                --border-color: #e2e8f0;
                --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.1);
            }}
            
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: 'Inter', sans-serif;
                background-color: var(--bg-primary);
                color: var(--text-primary);
            }}
            
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
            }}
            
            .header {{
                background: var(--primary-gradient);
                color: white;
                padding: 20px 30px;
                border-radius: 15px;
                margin-bottom: 30px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            
            .user-info {{
                display: flex;
                align-items: center;
                gap: 15px;
            }}
            
            .user-avatar {{
                width: 40px;
                height: 40px;
                background: var(--secondary-gradient);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-weight: bold;
            }}
            
            .nav-cards {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }}
            
            .nav-card {{
                background: var(--bg-card);
                padding: 25px;
                border-radius: 12px;
                border: 1px solid var(--border-color);
                cursor: pointer;
                transition: all 0.3s;
            }}
            
            .nav-card:hover {{
                transform: translateY(-5px);
                box-shadow: var(--shadow-md);
            }}
            
            .nav-card-icon {{
                font-size: 36px;
                margin-bottom: 15px;
                color: var(--accent-color);
            }}
            
            .content-section {{
                background: var(--bg-card);
                padding: 30px;
                border-radius: 12px;
                border: 1px solid var(--border-color);
                margin-bottom: 30px;
                display: none;
            }}
            
            .content-section.active {{
                display: block;
            }}
            
            .table-container {{
                overflow-x: auto;
                margin-top: 20px;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            
            th, td {{
                padding: 12px 15px;
                text-align: left;
                border-bottom: 1px solid var(--border-color);
            }}
            
            th {{
                background-color: #f8fafc;
                font-weight: 600;
            }}
            
            .badge {{
                padding: 5px 10px;
                border-radius: 15px;
                font-size: 12px;
                font-weight: 600;
            }}
            
            .badge-new {{ background: #dbeafe; color: #1e40af; }}
            .badge-process {{ background: #fef3c7; color: #92400e; }}
            .badge-completed {{ background: #d1fae5; color: #065f46; }}
            .badge-waiting {{ background: #f3e8ff; color: #6b21a8; }}
            
            .logout-btn {{
                padding: 8px 16px;
                background: rgba(255,255,255,0.2);
                border: none;
                color: white;
                border-radius: 8px;
                cursor: pointer;
            }}
            
            .logout-btn:hover {{
                background: rgba(255,255,255,0.3);
            }}
            
            .action-btn {{
                padding: 5px 10px;
                margin: 2px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 12px;
            }}
            
            .btn-view {{ background: #dbeafe; color: #1e40af; }}
            .btn-edit {{ background: #fef3c7; color: #92400e; }}
            .btn-assign {{ background: #dcfce7; color: #166534; }}
            .btn-comment {{ background: #e0e7ff; color: #3730a3; }}
            
            /* Модальное окно */
            .modal {{
                display: none;
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0,0,0,0.5);
                z-index: 1000;
                align-items: center;
                justify-content: center;
            }}
            
            .modal-content {{
                background: white;
                padding: 30px;
                border-radius: 10px;
                min-width: 300px;
                max-width: 800px;
                max-height: 80vh;
                overflow-y: auto;
            }}
            
            .modal-header {{
                margin-bottom: 20px;
                border-bottom: 1px solid var(--border-color);
                padding-bottom: 10px;
            }}
            
            .modal-footer {{
                margin-top: 20px;
                text-align: right;
                border-top: 1px solid var(--border-color);
                padding-top: 10px;
            }}
            
            .modal-btn {{
                padding: 8px 16px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                margin-left: 10px;
            }}
            
            .modal-btn-primary {{
                background: var(--accent-color);
                color: white;
            }}
            
            .modal-btn-secondary {{
                background: #ccc;
                color: black;
            }}
            
            .master-list {{
                max-height: 300px;
                overflow-y: auto;
                border: 1px solid var(--border-color);
                border-radius: 5px;
                padding: 10px;
            }}
            
            .master-item {{
                padding: 10px;
                border-bottom: 1px solid var(--border-color);
                cursor: pointer;
                transition: background 0.2s;
            }}
            
            .master-item:hover {{
                background: #f8fafc;
            }}
            
            .master-item.selected {{
                background: #e0e7ff;
                border-left: 4px solid var(--accent-color);
            }}
            
            .comments-section {{
                margin-top: 20px;
                border-top: 1px solid var(--border-color);
                padding-top: 20px;
            }}
            
            .comment-item {{
                background: #f8fafc;
                padding: 15px;
                margin-bottom: 10px;
                border-radius: 5px;
                border-left: 3px solid var(--accent-color);
            }}
            
            .comment-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 8px;
            }}
            
            .comment-author {{
                font-weight: bold;
                color: var(--text-primary);
            }}
            
            .comment-user-type {{
                font-size: 12px;
                color: var(--text-secondary);
                background: #e2e8f0;
                padding: 2px 8px;
                border-radius: 10px;
                margin-left: 10px;
            }}
            
            .comment-date {{
                font-size: 12px;
                color: var(--text-secondary);
            }}
            
            .comment-message {{
                margin-top: 5px;
                line-height: 1.5;
            }}
            
            .comment-source {{
                font-size: 10px;
                color: #94a3b8;
                margin-top: 5px;
                font-style: italic;
            }}
            
            .comment-from-file {{
                border-left-color: #10b981;
            }}
            
            .comment-from-system {{
                border-left-color: #3b82f6;
            }}
            
            .template-comment-item:hover {{
                background: #f1f5f9;
                border-color: #cbd5e1;
            }}
            
            .template-comment-item.selected {{
                background: #e0e7ff !important;
                border-color: #4f46e5 !important;
            }}
            
            .comment-template-list {{
                display: grid;
                gap: 8px;
                max-height: 200px;
                overflow-y: auto;
                padding: 10px;
                background: #f8fafc;
                border-radius: 8px;
                border: 1px solid #e2e8f0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div>
                    <h1>Сервисный центр "БытСервис"</h1>
                    <p>Учет заявок на ремонт бытовой техники</p>
                </div>
                <div class="user-info">
                    <div class="user-avatar">{user_name[0] if user_name else '?'}</div>
                    <div>
                        <div><strong>{user_name}</strong></div>
                        <div>{user_type_display}</div>
                    </div>
                    <button class="logout-btn" onclick="logout()">Выйти</button>
                </div>
            </div>
            
            <div class="nav-cards">
                <div class="nav-card" onclick="showSection('requests')">
                    <div class="nav-card-icon"><i class="fas fa-list"></i></div>
                    <h3>Все заявки</h3>
                    <p>Просмотр и управление заявками</p>
                </div>
                
                <div class="nav-card" onclick="showSection('new-request')" {'' if can_create_requests else 'style="display: none;"'}>
                    <div class="nav-card-icon"><i class="fas fa-plus-circle"></i></div>
                    <h3>Новая заявка</h3>
                    <p>Создание новой заявки на ремонт</p>
                </div>
                
                <div class="nav-card" onclick="showSection('stats')" {'' if can_view_stats else 'style="display: none;"'}>
                    <div class="nav-card-icon"><i class="fas fa-chart-bar"></i></div>
                    <h3>Статистика</h3>
                    <p>Аналитика и отчетность</p>
                </div>
                
                <div class="nav-card" onclick="showSection('masters')" {'' if can_view_masters else 'style="display: none;"'}>
                    <div class="nav-card-icon"><i class="fas fa-users"></i></div>
                    <h3>Мастера</h3>
                    <p>Управление мастерами</p>
                </div>
                
                <div class="nav-card" onclick="showSection('comments')">
                    <div class="nav-card-icon"><i class="fas fa-comments"></i></div>
                    <h3>Все комментарии</h3>
                    <p>Просмотр всех комментариев из файла и системы</p>
                </div>
            </div>
            
            <!-- Секция заявок -->
            <section id="requests" class="content-section active">
                <h2>{'Мои заявки' if user_type == 'master' else 'Все заявки'}</h2>
                <div>
                    <input type="text" id="searchInput" placeholder="Поиск по номеру, клиенту, описанию..." 
                           style="width: 100%; padding: 10px; margin-bottom: 20px;"
                           onkeyup="searchRequests()">
                    <div class="table-container">
                        <table id="requestsTable">
                            <thead>
                                <tr>
                                    <th>№</th>
                                    <th>Дата</th>
                                    <th>Тип техники</th>
                                    <th>Модель</th>
                                    <th>Проблема</th>
                                    <th>Клиент</th>
                                    <th>Статус</th>
                                    <th>Мастер</th>
                                    <th>Комментарии</th>
                                    <th>Действия</th>
                                </tr>
                            </thead>
                            <tbody id="requestsTableBody">
                                <tr><td colspan="10">Загрузка...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </section>
            
            <!-- Секция новой заявки -->
            <section id="new-request" class="content-section">
                <h2>Новая заявка на ремонт</h2>
                <form id="newRequestForm" style="max-width: 600px;">
                    <div style="display: grid; gap: 20px; margin-top: 20px;">
                        <div>
                            <label>Тип бытовой техники *</label>
                            <select id="tech_type" required style="width: 100%; padding: 10px;">
                                <option value="">Выберите тип техники</option>
                                <option value="Фен">Фен</option>
                                <option value="Тостер">Тостер</option>
                                <option value="Холодильник">Холодильник</option>
                                <option value="Стиральная машина">Стиральная машина</option>
                                <option value="Мультиварка">Мультиварка</option>
                                <option value="Телевизор">Телевизор</option>
                                <option value="Пылесос">Пылесос</option>
                                <option value="Микроволновая печь">Микроволновая печь</option>
                                <option value="Духовой шкаф">Духовой шкаф</option>
                                <option value="Посудомоечная машина">Посудомоечная машина</option>
                                <option value="Кондиционер">Кондиционер</option>
                                <option value="Обогреватель">Обогреватель</option>
                                <option value="Другое">Другое</option>
                            </select>
                        </div>
                        <div>
                            <label>Модель устройства *</label>
                            <input type="text" id="tech_model" required style="width: 100%; padding: 10px;" placeholder="Например: Ладомир ТА112 белый">
                        </div>
                        <div>
                            <label>Описание проблемы *</label>
                            <textarea id="problem_description" required style="width: 100%; padding: 10px; min-height: 100px;" placeholder="Подробное описание проблемы"></textarea>
                        </div>
                        <div>
                            <label>ФИО клиента *</label>
                            <input type="text" id="client_fio" required style="width: 100%; padding: 10px;" value="{user_name}" {'' if user_type == 'client' else ''}>
                        </div>
                        <div>
                            <label>Телефон клиента *</label>
                            <input type="tel" id="client_phone" required style="width: 100%; padding: 10px;" placeholder="+7 (XXX) XXX-XX-XX">
                        </div>
                        <div>
                            <label>Статус заявки</label>
                            <select id="request_status" style="width: 100%; padding: 10px;">
                                <option value="Новая заявка">Новая заявка</option>
                                <option value="В процессе ремонта">В процессе ремонта</option>
                                <option value="Ожидание запчастей">Ожидание запчастей</option>
                                <option value="Готова к выдаче">Готова к выдаче</option>
                            </select>
                        </div>
                        <button type="button" onclick="createNewRequest()" style="padding: 12px; background: var(--accent-color); color: white; border: none; border-radius: 8px; cursor: pointer;">
                            <i class="fas fa-plus"></i> Создать заявку
                        </button>
                    </div>
                </form>
            </section>
            
            <!-- Секция статистики -->
            <section id="stats" class="content-section">
                <h2>Статистика работы отдела обслуживания</h2>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0;">
                    <div style="background: #f8fafc; padding: 20px; border-radius: 10px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: var(--accent-color);" id="totalRequests">0</div>
                        <div>Всего заявок</div>
                    </div>
                    <div style="background: #f8fafc; padding: 20px; border-radius: 10px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #10b981;" id="completedRequests">0</div>
                        <div>Выполнено</div>
                    </div>
                    <div style="background: #f8fafc; padding: 20px; border-radius: 10px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #f59e0b;" id="avgTime">0</div>
                        <div>Среднее время (дней)</div>
                    </div>
                    <div style="background: #f8fafc; padding: 20px; border-radius: 10px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #8b5cf6;" id="inProcess">0</div>
                        <div>В процессе</div>
                    </div>
                </div>
                <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                    <div style="flex: 1; min-width: 300px;">
                        <canvas id="statusChart" style="max-width: 100%;"></canvas>
                    </div>
                    <div style="flex: 1; min-width: 300px;">
                        <canvas id="typeChart" style="max-width: 100%;"></canvas>
                    </div>
                </div>
                <div style="margin-top: 30px;">
                    <h3>Статистика по типам неисправностей</h3>
                    <div id="problemStats" style="margin-top: 10px;">
                        <!-- Статистика будет загружена здесь -->
                    </div>
                </div>
            </section>
            
            <!-- Секция мастеров -->
            <section id="masters" class="content-section">
                <h2>Мастера</h2>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>ФИО</th>
                                <th>Телефон</th>
                                <th>Логин</th>
                                <th>Тип</th>
                                <th>Заявок в работе</th>
                                <th>Всего заявок</th>
                                <th>Комментариев</th>
                            </tr>
                        </thead>
                        <tbody id="mastersTableBody">
                            <tr><td colspan="7">Загрузка...</td></tr>
                        </tbody>
                    </table>
                </div>
            </section>
            
            <!-- Секция комментариев -->
            <section id="comments" class="content-section">
                <h2>Все комментарии из файла и системы</h2>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Заявка</th>
                                <th>Автор</th>
                                <th>Тип автора</th>
                                <th>Комментарий</th>
                                <th>Дата</th>
                                <th>Источник</th>
                            </tr>
                        </thead>
                        <tbody id="commentsTableBody">
                            <tr><td colspan="7">Загрузка...</td></tr>
                        </tbody>
                    </table>
                </div>
                <div style="margin-top: 20px; display: flex; gap: 10px;">
                    <div style="display: flex; align-items: center;">
                        <div style="width: 15px; height: 15px; background-color: #10b981; margin-right: 5px;"></div>
                        <span>Комментарии из файла</span>
                    </div>
                    <div style="display: flex; align-items: center;">
                        <div style="width: 15px; height: 15px; background-color: #3b82f6; margin-right: 5px;"></div>
                        <span>Комментарии из системы</span>
                    </div>
                </div>
            </section>
        </div>
        
        <!-- Модальное окно для назначения мастера -->
        <div id="assignMasterModal" class="modal">
            <div class="modal-content">
                <div class="modal-header">
                    <h3>Назначить мастера</h3>
                </div>
                <div id="assignMasterModalBody">
                    <p>Выберите мастера для назначения на заявку:</p>
                    <div class="master-list" id="masterList">
                        <!-- Список мастеров будет загружен здесь -->
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="modal-btn modal-btn-primary" onclick="confirmAssignMaster()">Назначить</button>
                    <button class="modal-btn modal-btn-secondary" onclick="closeAssignMasterModal()">Отмена</button>
                </div>
            </div>
        </div>
        
        <!-- Модальное окно для просмотра заявки с комментариями -->
        <div id="viewRequestModal" class="modal">
            <div class="modal-content">
                <div class="modal-header">
                    <h3 id="viewRequestTitle">Заявка №</h3>
                </div>
                <div id="viewRequestBody">
                    <!-- Информация о заявке и комментарии будут загружены здесь -->
                </div>
                <div class="modal-footer">
                    <button class="modal-btn modal-btn-secondary" onclick="closeViewRequestModal()">Закрыть</button>
                </div>
            </div>
        </div>
        
        <!-- Модальное окно для добавления комментария -->
        <div id="addCommentModal" class="modal">
            <div class="modal-content">
                <div class="modal-header">
                    <h3>Добавить комментарий</h3>
                </div>
                <div id="addCommentModalBody">
                    <div style="margin-bottom: 20px;">
                        <label>Выберите готовый комментарий:</label>
                        <div id="templateComments" style="display: grid; gap: 5px; margin-top: 10px; max-height: 150px; overflow-y: auto; border: 1px solid var(--border-color); padding: 10px; border-radius: 5px;">
                            <!-- Готовые комментарии будут загружены здесь -->
                        </div>
                    </div>
                    
                    <div style="margin-bottom: 20px;">
                        <label>Или введите свой комментарий:</label>
                        <textarea id="commentMessage" style="width: 100%; padding: 10px; min-height: 100px;" placeholder="Введите комментарий"></textarea>
                    </div>
                    
                    <div style="margin-top: 10px;">
                        <label>Запасные части (если требуется):</label>
                        <input type="text" id="repairParts" style="width: 100%; padding: 10px;" placeholder="Укажите использованные запчасти">
                    </div>
                    
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 15px;">
                        <div>
                            <button type="button" onclick="clearComment()" style="padding: 5px 10px; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 5px; cursor: pointer;">
                                <i class="fas fa-times"></i> Очистить
                            </button>
                        </div>
                        <div>
                            <button class="modal-btn modal-btn-secondary" onclick="closeAddCommentModal()">Отмена</button>
                            <button class="modal-btn modal-btn-primary" onclick="confirmAddComment()">Добавить</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            let currentAssignRequestId = null;
            let selectedMasterId = null;
            let currentEditRequestId = null;
            let currentCommentRequestId = null;
            let currentViewRequestId = null;
            
            // Показ секций
            function showSection(sectionId) {{
                document.querySelectorAll('.content-section').forEach(section => {{
                    section.classList.remove('active');
                }});
                document.getElementById(sectionId).classList.add('active');
                
                // Загрузка данных для секции
                if (sectionId === 'requests') loadRequests();
                if (sectionId === 'stats') loadStats();
                if (sectionId === 'masters') loadMasters();
                if (sectionId === 'comments') loadComments();
            }}
            
            // Загрузка заявок
            async function loadRequests() {{
                try {{
                    const response = await fetch('/api/requests');
                    const requests = await response.json();
                    
                    const tbody = document.getElementById('requestsTableBody');
                    tbody.innerHTML = '';
                    
                    if (requests.length === 0) {{
                        tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; padding: 20px;">Нет заявок</td></tr>';
                        return;
                    }}
                    
                    for (const request of requests) {{
                        const row = document.createElement('tr');
                        const statusClass = {{
                            'Новая заявка': 'badge-new',
                            'В процессе ремонта': 'badge-process',
                            'Готова к выдаче': 'badge-completed',
                            'Завершена': 'badge-completed',
                            'Ожидание запчастей': 'badge-waiting'
                        }}[request.request_status] || 'badge-new';
                        
                        let actionButtons = '';
                        const userType = '{user_type}';
                        
                        // Получаем количество комментариев для этой заявки
                        const commentCount = request.has_comment ? await getCommentCount(request.request_id) : 0;
                        
                        if (userType === 'admin' || userType === 'manager' || userType === 'operator') {{
                            actionButtons = `
                                <button class="action-btn btn-view" onclick="viewRequestDetails(${{request.request_id}})">Просмотр</button>
                                <button class="action-btn btn-assign" onclick="openAssignMasterModal(${{request.request_id}})">Назначить</button>
                                <button class="action-btn btn-comment" onclick="openAddCommentModal(${{request.request_id}})">Комментарий</button>
                            `;
                        }} else if (userType === 'master') {{
                            actionButtons = `
                                <button class="action-btn btn-view" onclick="viewRequestDetails(${{request.request_id}})">Просмотр</button>
                                <button class="action-btn btn-comment" onclick="openAddCommentModal(${{request.request_id}})">Комментарий</button>
                            `;
                        }} else {{
                            actionButtons = `
                                <button class="action-btn btn-view" onclick="viewRequestDetails(${{request.request_id}})">Просмотр</button>
                            `;
                        }}
                        
                        row.innerHTML = `
                            <td>${{request.request_id}}</td>
                            <td>${{new Date(request.start_date).toLocaleDateString('ru-RU')}}</td>
                            <td>${{request.tech_type}}</td>
                            <td>${{request.tech_model}}</td>
                            <td>${{request.problem_description}}</td>
                            <td>${{request.client_fio}}<br><small>${{request.client_phone}}</small></td>
                            <td><span class="badge ${{statusClass}}">${{request.request_status}}</span></td>
                            <td>${{request.master_fio || 'Не назначен'}}</td>
                            <td>${{commentCount > 0 ? commentCount + ' комментариев' : 'Нет'}}</td>
                            <td>${{actionButtons}}</td>
                        `;
                        tbody.appendChild(row);
                    }}
                }} catch (error) {{
                    console.error('Ошибка загрузки заявок:', error);
                    document.getElementById('requestsTableBody').innerHTML = '<tr><td colspan="10" style="text-align: center; color: red;">Ошибка загрузки данных</td></tr>';
                }}
            }}
            
            // Получение количества комментариев для заявки
            async function getCommentCount(requestId) {{
                try {{
                    const response = await fetch('/api/comments/request/' + requestId);
                    const comments = await response.json();
                    return comments.length;
                }} catch (error) {{
                    return 0;
                }}
            }}
            
            // Поиск заявок
            async function searchRequests() {{
                const query = document.getElementById('searchInput').value;
                if (query.length < 2 && query.length > 0) return;
                
                try {{
                    const response = await fetch('/api/requests/search?q=' + encodeURIComponent(query));
                    const requests = await response.json();
                    
                    const tbody = document.getElementById('requestsTableBody');
                    tbody.innerHTML = '';
                    
                    if (requests.length === 0) {{
                        tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; padding: 20px;">Ничего не найдено</td></tr>';
                        return;
                    }}
                    
                    for (const request of requests) {{
                        const row = document.createElement('tr');
                        const statusClass = {{
                            'Новая заявка': 'badge-new',
                            'В процессе ремонта': 'badge-process',
                            'Готова к выдаче': 'badge-completed',
                            'Завершена': 'badge-completed',
                            'Ожидание запчастей': 'badge-waiting'
                        }}[request.request_status] || 'badge-new';
                        
                        let actionButtons = '';
                        const userType = '{user_type}';
                        
                        // Получаем количество комментариев для этой заявки
                        const commentCount = request.has_comment ? await getCommentCount(request.request_id) : 0;
                        
                        if (userType === 'admin' || userType === 'manager' || userType === 'operator') {{
                            actionButtons = `
                                <button class="action-btn btn-view" onclick="viewRequestDetails(${{request.request_id}})">Просмотр</button>
                                <button class="action-btn btn-assign" onclick="openAssignMasterModal(${{request.request_id}})">Назначить</button>
                                <button class="action-btn btn-comment" onclick="openAddCommentModal(${{request.request_id}})">Комментарий</button>
                            `;
                        }} else if (userType === 'master') {{
                            actionButtons = `
                                <button class="action-btn btn-view" onclick="viewRequestDetails(${{request.request_id}})">Просмотр</button>
                                <button class="action-btn btn-comment" onclick="openAddCommentModal(${{request.request_id}})">Комментарий</button>
                            `;
                        }} else {{
                            actionButtons = `
                                <button class="action-btn btn-view" onclick="viewRequestDetails(${{request.request_id}})">Просмотр</button>
                            `;
                        }}
                        
                        row.innerHTML = `
                            <td>${{request.request_id}}</td>
                            <td>${{new Date(request.start_date).toLocaleDateString('ru-RU')}}</td>
                            <td>${{request.tech_type}}</td>
                            <td>${{request.tech_model}}</td>
                            <td>${{request.problem_description}}</td>
                            <td>${{request.client_fio}}<br><small>${{request.client_phone}}</small></td>
                            <td><span class="badge ${{statusClass}}">${{request.request_status}}</span></td>
                            <td>${{request.master_fio || 'Не назначен'}}</td>
                            <td>${{commentCount > 0 ? commentCount + ' комментариев' : 'Нет'}}</td>
                            <td>${{actionButtons}}</td>
                        `;
                        tbody.appendChild(row);
                    }}
                }} catch (error) {{
                    console.error('Ошибка поиска:', error);
                }}
            }}
            
            // Загрузка шаблонов комментариев
            async function loadTemplateComments() {{
                try {{
                    const response = await fetch('/api/template_comments');
                    const templateComments = await response.json();
                    
                    const container = document.getElementById('templateComments');
                    container.innerHTML = '';
                    
                    if (templateComments.length === 0) {{
                        container.innerHTML = '<div style="text-align: center; color: #666; padding: 20px;">Нет доступных шаблонов комментариев</div>';
                        return;
                    }}
                    
                    templateComments.forEach((comment, index) => {{
                        const commentItem = document.createElement('div');
                        commentItem.className = 'template-comment-item';
                        commentItem.style.cssText = `
                            padding: 8px 12px;
                            background: #f8fafc;
                            border: 1px solid #e2e8f0;
                            border-radius: 5px;
                            cursor: pointer;
                            font-size: 14px;
                            transition: all 0.2s;
                            margin-bottom: 5px;
                        `;
                        
                        commentItem.innerHTML = `
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span>${{comment}}</span>
                                <i class="fas fa-plus" style="color: #4f46e5; font-size: 12px;"></i>
                            </div>
                        `;
                        
                        commentItem.onclick = () => {{
                            // Выделяем выбранный шаблон
                            document.querySelectorAll('.template-comment-item').forEach(item => {{
                                item.style.background = '#f8fafc';
                                item.style.borderColor = '#e2e8f0';
                            }});
                            
                            commentItem.style.background = '#e0e7ff';
                            commentItem.style.borderColor = '#4f46e5';
                            
                            // Вставляем текст в поле
                            document.getElementById('commentMessage').value = comment;
                        }};
                        
                        commentItem.onmouseover = () => {{
                            if (commentItem.style.background !== '#e0e7ff') {{
                                commentItem.style.background = '#f1f5f9';
                            }}
                        }};
                        
                        commentItem.onmouseout = () => {{
                            if (commentItem.style.background !== '#e0e7ff') {{
                                commentItem.style.background = '#f8fafc';
                            }}
                        }};
                        
                        container.appendChild(commentItem);
                    }});
                    
                }} catch (error) {{
                    console.error('Ошибка загрузки шаблонов комментариев:', error);
                }}
            }}
            
            // Очистка комментария
            function clearComment() {{
                document.getElementById('commentMessage').value = '';
                document.querySelectorAll('.template-comment-item').forEach(item => {{
                    item.style.background = '#f8fafc';
                    item.style.borderColor = '#e2e8f0';
                }});
            }}
            
            // Просмотр деталей заявки с комментариями
            async function viewRequestDetails(requestId) {{
                currentViewRequestId = requestId;
                
                try {{
                    const response = await fetch('/api/requests/' + requestId);
                    const requestData = await response.json();
                    
                    // Загружаем комментарии для этой заявки
                    const commentsResponse = await fetch('/api/comments/request/' + requestId);
                    const comments = await commentsResponse.json();
                    
                    document.getElementById('viewRequestTitle').textContent = `Заявка №${{requestId}}`;
                    
                    let masterInfo = 'Не назначен';
                    if (requestData.master_fio) {{
                        masterInfo = `${{requestData.master_fio}} (${{requestData.master_phone}})`;
                    }}
                    
                    let partsInfo = 'Не указаны';
                    if (requestData.repair_parts) {{
                        partsInfo = requestData.repair_parts;
                    }}
                    
                    let commentsHtml = '<h3>Комментарии:</h3>';
                    if (comments.length === 0) {{
                        commentsHtml += '<p>Нет комментариев</p>';
                    }} else {{
                        // Сортируем комментарии по дате (новые сверху)
                        comments.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
                        
                        comments.forEach(comment => {{
                            const sourceClass = comment.comment_id ? 'comment-from-file' : 'comment-from-system';
                            const sourceText = comment.comment_id ? 'Из файла' : 'Из системы';
                            const userTypeDisplay = {{
                                'admin': 'Администратор',
                                'manager': 'Менеджер',
                                'master': 'Мастер',
                                'operator': 'Оператор',
                                'client': 'Заказчик'
                            }}[comment.user_type] || comment.user_type;
                            
                            commentsHtml += `
                                <div class="comment-item ${{sourceClass}}">
                                    <div class="comment-header">
                                        <div>
                                            <span class="comment-author">${{comment.user_fio || 'Неизвестный автор'}}</span>
                                            <span class="comment-user-type">${{userTypeDisplay}}</span>
                                        </div>
                                        <div class="comment-date">${{new Date(comment.created_at).toLocaleString('ru-RU')}}</div>
                                    </div>
                                    <div class="comment-message">${{comment.message}}</div>
                                    <div class="comment-source">Источник: ${{sourceText}}</div>
                                </div>
                            `;
                        }});
                    }}
                    
                    // Добавляем кнопку для добавления комментария, если у пользователя есть права
                    let addCommentButton = '';
                    const userType = '{user_type}';
                    if (userType !== 'client') {{
                        addCommentButton = `
                            <div style="margin-top: 20px; border-top: 1px solid var(--border-color); padding-top: 20px;">
                                <button onclick="openAddCommentModal(${{requestId}})" style="padding: 10px 20px; background: var(--accent-color); color: white; border: none; border-radius: 5px; cursor: pointer;">
                                    <i class="fas fa-plus"></i> Добавить комментарий
                                </button>
                            </div>
                        `;
                    }}
                    
                    const modalBody = `
                        <div style="padding: 20px;">
                            <p><strong>Дата создания:</strong> ${{new Date(requestData.start_date).toLocaleDateString('ru-RU')}}</p>
                            <p><strong>Тип техники:</strong> ${{requestData.tech_type}}</p>
                            <p><strong>Модель:</strong> ${{requestData.tech_model}}</p>
                            <p><strong>Проблема:</strong> ${{requestData.problem_description}}</p>
                            <p><strong>Клиент:</strong> ${{requestData.client_fio}} (${{requestData.client_phone}})</p>
                            <p><strong>Статус:</strong> ${{requestData.request_status}}</p>
                            <p><strong>Мастер:</strong> ${{masterInfo}}</p>
                            <p><strong>Запасные части:</strong> ${{partsInfo}}</p>
                            ${{requestData.completion_date ? 
                                '<p><strong>Дата завершения:</strong> ' + new Date(requestData.completion_date).toLocaleDateString('ru-RU') + '</p>' : ''}}
                            <div class="comments-section">
                                ${{commentsHtml}}
                            </div>
                            ${{addCommentButton}}
                        </div>
                    `;
                    
                    document.getElementById('viewRequestBody').innerHTML = modalBody;
                    document.getElementById('viewRequestModal').style.display = 'flex';
                    
                }} catch (error) {{
                    console.error('Ошибка загрузки данных заявки:', error);
                    alert('Ошибка загрузки данных заявки');
                }}
            }}
            
            // Закрытие модального окна просмотра заявки
            function closeViewRequestModal() {{
                document.getElementById('viewRequestModal').style.display = 'none';
                currentViewRequestId = null;
            }}
            
            // Открытие модального окна для назначения мастера
            async function openAssignMasterModal(requestId) {{
                if (!{json.dumps(can_assign_masters)}) {{
                    alert('У вас нет прав для назначения мастеров');
                    return;
                }}
                
                currentAssignRequestId = requestId;
                selectedMasterId = null;
                
                try {{
                    const response = await fetch('/api/masters');
                    const masters = await response.json();
                    
                    const masterList = document.getElementById('masterList');
                    masterList.innerHTML = '';
                    
                    if (masters.length === 0) {{
                        masterList.innerHTML = '<p style="text-align: center; padding: 20px;">Нет доступных мастеров</p>';
                    }} else {{
                        masters.forEach(master => {{
                            const masterItem = document.createElement('div');
                            masterItem.className = 'master-item';
                            masterItem.onclick = () => selectMaster(master.id, masterItem);
                            
                            masterItem.innerHTML = `
                                <div class="master-info">
                                    <div>
                                        <div class="master-name">${{master.master_fio}}</div>
                                        <div style="font-size: 12px; color: #666; margin-top: 2px;">${{master.master_phone}}</div>
                                    </div>
                                </div>
                                <div style="font-size: 12px; color: #666; margin-top: 5px;">
                                    Заявок в работе: <strong>${{master.active_requests || 0}}</strong>
                                </div>
                            `;
                            
                            masterList.appendChild(masterItem);
                        }});
                    }}
                    
                    document.getElementById('assignMasterModal').style.display = 'flex';
                }} catch (error) {{
                    console.error('Ошибка загрузки мастеров:', error);
                    alert('Ошибка загрузки списка мастеров');
                }}
            }}
            
            // Выбор мастера
            function selectMaster(masterId, element) {{
                selectedMasterId = masterId;
                
                document.querySelectorAll('.master-item').forEach(item => {{
                    item.classList.remove('selected');
                }});
                
                element.classList.add('selected');
            }}
            
            // Подтверждение назначения мастера
            async function confirmAssignMaster() {{
                if (!selectedMasterId) {{
                    alert('Выберите мастера');
                    return;
                }}
                
                try {{
                    const response = await fetch('/api/requests/' + currentAssignRequestId + '/assign', {{
                        method: 'PUT',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ master_id: selectedMasterId }})
                    }});
                    
                    const result = await response.json();
                    if (result.success) {{
                        alert('Мастер успешно назначен на заявку');
                        closeAssignMasterModal();
                        loadRequests();
                        loadStats();
                    }} else {{
                        alert('Ошибка: ' + result.error);
                    }}
                }} catch (error) {{
                    alert('Ошибка соединения с сервером');
                }}
            }}
            
            // Закрытие модального окна назначения мастера
            function closeAssignMasterModal() {{
                document.getElementById('assignMasterModal').style.display = 'none';
                currentAssignRequestId = null;
                selectedMasterId = null;
            }}
            
            // Открытие модального окна для добавления комментария
            async function openAddCommentModal(requestId) {{
                currentCommentRequestId = requestId;
                
                // Сбрасываем состояние
                document.getElementById('commentMessage').value = '';
                document.getElementById('repairParts').value = '';
                document.querySelectorAll('.template-comment-item').forEach(item => {{
                    item.style.background = '#f8fafc';
                    item.style.borderColor = '#e2e8f0';
                }});
                
                // Загружаем шаблоны
                await loadTemplateComments();
                
                document.getElementById('addCommentModal').style.display = 'flex';
            }}
            
            // Подтверждение добавления комментария
            async function confirmAddComment() {{
                const comment = document.getElementById('commentMessage').value;
                const repairParts = document.getElementById('repairParts').value;
                
                if (!comment) {{
                    alert('Введите комментарий или выберите из списка');
                    return;
                }}
                
                try {{
                    const response = await fetch('/api/comments', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            request_id: currentCommentRequestId,
                            message: comment,
                            repair_parts: repairParts
                        }})
                    }});
                    
                    const result = await response.json();
                    if (result.success) {{
                        alert('Комментарий успешно добавлен');
                        closeAddCommentModal();
                        loadRequests();
                        loadComments();
                        
                        // Обновляем детали заявки, если открыто окно просмотра
                        if (currentViewRequestId === currentCommentRequestId) {{
                            viewRequestDetails(currentViewRequestId);
                        }}
                    }} else {{
                        alert('Ошибка: ' + result.error);
                    }}
                }} catch (error) {{
                    alert('Ошибка соединения с сервером');
                }}
            }}
            
            // Закрытие модального окна добавления комментария
            function closeAddCommentModal() {{
                document.getElementById('addCommentModal').style.display = 'none';
                document.getElementById('commentMessage').value = '';
                document.getElementById('repairParts').value = '';
                currentCommentRequestId = null;
            }}
            
            // Создание новой заявки
            async function createNewRequest() {{
                const formData = {{
                    tech_type: document.getElementById('tech_type').value,
                    tech_model: document.getElementById('tech_model').value,
                    problem_description: document.getElementById('problem_description').value,
                    client_fio: document.getElementById('client_fio').value,
                    client_phone: document.getElementById('client_phone').value,
                    request_status: document.getElementById('request_status').value
                }};
                
                if (!formData.tech_type || !formData.tech_model || !formData.problem_description || 
                    !formData.client_fio || !formData.client_phone) {{
                    alert('Пожалуйста, заполните все обязательные поля');
                    return;
                }}
                
                try {{
                    const response = await fetch('/api/requests', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(formData)
                    }});
                    
                    const result = await response.json();
                    if (result.success) {{
                        alert('Заявка №' + result.request_id + ' успешно создана!');
                        document.getElementById('newRequestForm').reset();
                        document.getElementById('client_fio').value = '{user_name}';
                        showSection('requests');
                        loadRequests();
                        loadStats();
                    }} else {{
                        alert('Ошибка: ' + result.error);
                    }}
                }} catch (error) {{
                    alert('Ошибка соединения с сервером');
                }}
            }}
            
            // Загрузка статистики
            async function loadStats() {{
                try {{
                    const response = await fetch('/api/stats');
                    const stats = await response.json();
                    
                    document.getElementById('totalRequests').textContent = stats.total_requests;
                    document.getElementById('completedRequests').textContent = stats.completed_requests;
                    document.getElementById('avgTime').textContent = stats.avg_days || '0';
                    document.getElementById('inProcess').textContent = stats.in_process;
                    
                    // График распределения по статусам
                    const statusCtx = document.getElementById('statusChart').getContext('2d');
                    if (window.statusChart) {{
                        window.statusChart.destroy();
                    }}
                    window.statusChart = new Chart(statusCtx, {{
                        type: 'doughnut',
                        data: {{
                            labels: stats.status_distribution.map(item => item.status),
                            datasets: [{{
                                data: stats.status_distribution.map(item => item.count),
                                backgroundColor: ['#3b82f6', '#f59e0b', '#10b981', '#8b5cf6', '#ef4444']
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            plugins: {{
                                title: {{
                                    display: true,
                                    text: 'Распределение по статусам'
                                }}
                            }}
                        }}
                    }});
                    
                    // График распределения по типам оборудования
                    const typeCtx = document.getElementById('typeChart').getContext('2d');
                    if (window.typeChart) {{
                        window.typeChart.destroy();
                    }}
                    window.typeChart = new Chart(typeCtx, {{
                        type: 'bar',
                        data: {{
                            labels: stats.type_distribution.map(item => item.tech_type),
                            datasets: [{{
                                label: 'Количество',
                                data: stats.type_distribution.map(item => item.count),
                                backgroundColor: '#4facfe'
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            plugins: {{
                                title: {{
                                    display: true,
                                    text: 'Распределение по типам оборудования'
                                }}
                            }}
                        }}
                    }});
                    
                    // Статистика по проблемам
                    const problemStatsDiv = document.getElementById('problemStats');
                    let problemStatsHtml = '<ul>';
                    stats.problem_stats.forEach(item => {{
                        problemStatsHtml += `<li><strong>${{item.problem_type}}:</strong> ${{item.count}} заявок (${{item.percentage}}%)</li>`;
                    }});
                    problemStatsHtml += '</ul>';
                    problemStatsDiv.innerHTML = problemStatsHtml;
                    
                }} catch (error) {{
                    console.error('Ошибка загрузки статистики:', error);
                }}
            }}
            
            // Загрузка мастеров
            async function loadMasters() {{
                try {{
                    const response = await fetch('/api/masters');
                    const masters = await response.json();
                    
                    const tbody = document.getElementById('mastersTableBody');
                    tbody.innerHTML = '';
                    
                    masters.forEach(master => {{
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${{master.master_fio}}</td>
                            <td>${{master.master_phone}}</td>
                            <td>${{master.master_login}}</td>
                            <td>${{master.master_type}}</td>
                            <td>${{master.active_requests || 0}}</td>
                            <td>${{master.total_requests || 0}}</td>
                            <td>${{master.comment_count || 0}}</td>
                        `;
                        tbody.appendChild(row);
                    }});
                }} catch (error) {{
                    console.error('Ошибка загрузки мастеров:', error);
                }}
            }}
            
            // Загрузка комментариев
            async function loadComments() {{
                try {{
                    const response = await fetch('/api/comments');
                    const comments = await response.json();
                    
                    const tbody = document.getElementById('commentsTableBody');
                    tbody.innerHTML = '';
                    
                    if (comments.length === 0) {{
                        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 20px;">Нет комментариев</td></tr>';
                        return;
                    }}
                    
                    comments.forEach(comment => {{
                        const row = document.createElement('tr');
                        const sourceText = comment.comment_id ? 'Файл' : 'Система';
                        const sourceClass = comment.comment_id ? 'comment-from-file' : 'comment-from-system';
                        const userTypeDisplay = {{
                            'admin': 'Администратор',
                            'manager': 'Менеджер',
                            'master': 'Мастер',
                            'operator': 'Оператор',
                            'client': 'Заказчик'
                        }}[comment.user_type] || comment.user_type;
                        
                        row.innerHTML = `
                            <td>${{comment.id}}</td>
                            <td>Заявка №${{comment.request_id}}</td>
                            <td>${{comment.user_fio || 'Неизвестно'}}</td>
                            <td>${{userTypeDisplay}}</td>
                            <td>${{comment.message}}</td>
                            <td>${{new Date(comment.created_at).toLocaleDateString('ru-RU')}}</td>
                            <td><span class="badge" style="background: ${{comment.comment_id ? '#10b981' : '#3b82f6'}}">${{sourceText}}</span></td>
                        `;
                        tbody.appendChild(row);
                    }});
                }} catch (error) {{
                    console.error('Ошибка загрузки комментариев:', error);
                }}
            }}
            
            // Выход из системы без сообщений об ошибок
            async function logout() {{
                try {{
                    await fetch('/api/logout');
                }} catch (error) {{
                    // Игнорируем любые ошибки соединения
                }}
                // Всегда перенаправляем на главную страницу
                window.location.href = '/';
            }}
            
            // Инициализация при загрузке
            document.addEventListener('DOMContentLoaded', () => {{
                console.log('DOM загружен, инициализация приложения');
                loadRequests();
                loadStats();
                
                // Закрытие модальных окон при клике вне их
                document.addEventListener('click', (event) => {{
                    if (event.target.classList.contains('modal')) {{
                        event.target.style.display = 'none';
                    }}
                }});
                
                // Добавляем обработчик для кнопки выхода через addEventListener для надежности
                const logoutBtn = document.querySelector('.logout-btn');
                if (logoutBtn) {{
                    logoutBtn.addEventListener('click', logout);
                    console.log('Обработчик для кнопки выхода добавлен');
                }}
            }});
        </script>
    </body>
    </html>
    '''
    return main_html

# ========== API маршруты ==========

@app.route('/api/template_comments')
def get_template_comments():
    """Получение готовых комментариев из файла"""
    try:
        conn = sqlite3.connect('service_requests.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Получаем уникальные комментарии из файла (где comment_id не NULL)
        cursor.execute('''
            SELECT DISTINCT message 
            FROM comments 
            WHERE comment_id IS NOT NULL 
            ORDER BY message
        ''')
        rows = cursor.fetchall()
        conn.close()
        
        template_comments = [row['message'] for row in rows]
        
        # Добавляем стандартные варианты, если файл пустой
        if not template_comments:
            template_comments = [
                "Интересная поломка",
                "Очень странно, будем разбираться!",
                "Скорее всего потребуется мотор обдува!",
                "Требуется замена детали",
                "Диагностика выполнена",
                "Ремонт завершен успешно"
            ]
        
        return jsonify(template_comments)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/logout')
def logout_api():
    """Выход из системы"""
    try:
        print(f"Пользователь {session.get('user_login', 'неизвестный')} выходит из системы")
        session.clear()
        print("Сессия успешно очищена")
        return jsonify({"success": True})
    except Exception as e:
        print(f"Ошибка при выходе: {str(e)}")
        # Возвращаем успех в любом случае, чтобы не показывать ошибку пользователю
        return jsonify({"success": True})

@app.route('/api/requests')
def get_requests():
    """Получение всех заявок"""
    try:
        conn = sqlite3.connect('service_requests.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        user_type = session.get('user_type')
        user_login = session.get('user_login')
        
        if user_type == 'client':
            cursor.execute('''
                SELECT * FROM service_requests 
                WHERE client_login = ? 
                ORDER BY start_date DESC
            ''', (user_login,))
        elif user_type == 'master':
            cursor.execute("SELECT id FROM masters WHERE master_login = ?", (user_login,))
            master_result = cursor.fetchone()
            
            if master_result:
                master_id = master_result[0]
                cursor.execute('''
                    SELECT * FROM service_requests 
                    WHERE master_id = ?
                    ORDER BY start_date DESC
                ''', (master_id,))
            else:
                return jsonify([])
        else:
            cursor.execute('''
                SELECT * FROM service_requests 
                ORDER BY start_date DESC
            ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/requests/<int:request_id>')
def get_request(request_id):
    """Получение конкретной заявки"""
    try:
        conn = sqlite3.connect('service_requests.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM service_requests WHERE request_id = ?
        ''', (request_id,))
        
        request_data = cursor.fetchone()
        conn.close()
        
        if request_data:
            return jsonify(dict(request_data))
        else:
            return jsonify({"error": "Заявка не найдена"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/requests', methods=['POST'])
def create_request():
    """Создание новой заявки"""
    try:
        data = request.json
        
        if 'user_id' not in session:
            return jsonify({"success": False, "error": "Требуется авторизация"}), 401
        
        conn = sqlite3.connect('service_requests.db')
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(request_id) FROM service_requests")
        max_id = cursor.fetchone()[0] or 0
        new_request_id = max_id + 1
        
        cursor.execute('''
            INSERT INTO service_requests (
                request_id, start_date, tech_type, tech_model, problem_description,
                request_status, client_fio, client_phone, client_login, client_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            new_request_id,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            data['tech_type'],
            data['tech_model'],
            data['problem_description'],
            data.get('request_status', 'Новая заявка'),
            data['client_fio'],
            data['client_phone'],
            session.get('user_login', ''),
            'client'
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "request_id": new_request_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/requests/<int:request_id>/assign', methods=['PUT'])
def assign_master(request_id):
    """Назначение мастера на заявку"""
    try:
        data = request.json
        user_type = session.get('user_type')
        
        if user_type not in ['admin', 'manager', 'operator']:
            return jsonify({"success": False, "error": "Недостаточно прав"}), 403
        
        master_id = data.get('master_id')
        if not master_id:
            return jsonify({"success": False, "error": "Не указан ID мастера"}), 400
        
        conn = sqlite3.connect('service_requests.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT master_fio, master_phone, master_login FROM masters WHERE id = ?", (master_id,))
        master = cursor.fetchone()
        
        if not master:
            return jsonify({"success": False, "error": "Мастер не найден"}), 404
        
        cursor.execute('''
            UPDATE service_requests 
            SET master_id = ?, master_fio = ?, master_phone = ?, master_login = ?,
                request_status = 'В процессе ремонта'
            WHERE request_id = ?
        ''', (master_id, master[0], master[1], master[2], request_id))
        
        cursor.execute('''
            INSERT INTO status_history (request_id, old_status, new_status, changed_by, comment)
            VALUES (?, ?, ?, ?, ?)
        ''', (request_id, 'Новая заявка', 'В процессе ремонта', 
              session.get('user_name', 'Система'), f'Назначен мастер: {master[0]}'))
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/stats')
def get_stats():
    """Получение статистики"""
    try:
        conn = sqlite3.connect('service_requests.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM service_requests")
        total_requests = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM service_requests WHERE request_status = 'Готова к выдаче' OR request_status = 'Завершена'")
        completed_requests = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM service_requests WHERE request_status = 'В процессе ремонта'")
        in_process = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT AVG(days_in_process) 
            FROM service_requests 
            WHERE (request_status = 'Готова к выдаче' OR request_status = 'Завершена') 
            AND days_in_process IS NOT NULL AND days_in_process > 0
        ''')
        avg_days = cursor.fetchone()[0]
        avg_days = round(avg_days, 1) if avg_days else 0
        
        cursor.execute('''
            SELECT request_status, COUNT(*) as count 
            FROM service_requests 
            GROUP BY request_status
        ''')
        status_distribution = [{"status": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        cursor.execute('''
            SELECT tech_type, COUNT(*) as count 
            FROM service_requests 
            GROUP BY tech_type
        ''')
        type_distribution = [{"tech_type": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        # Статистика по типам проблем (упрощенная)
        cursor.execute('''
            SELECT 
                CASE 
                    WHEN LOWER(problem_description) LIKE '%не работает%' OR LOWER(problem_description) LIKE '%перестал%' THEN 'Не работает'
                    WHEN LOWER(problem_description) LIKE '%мороз%' OR LOWER(problem_description) LIKE '%холод%' THEN 'Проблемы с охлаждением'
                    WHEN LOWER(problem_description) LIKE '%гудит%' OR LOWER(problem_description) LIKE '%шум%' THEN 'Шум/вибрация'
                    WHEN LOWER(problem_description) LIKE '%включаться%' OR LOWER(problem_description) LIKE '%запуск%' THEN 'Проблемы с включением'
                    ELSE 'Другое'
                END as problem_type,
                COUNT(*) as count
            FROM service_requests 
            GROUP BY problem_type
        ''')
        
        problem_stats_raw = cursor.fetchall()
        total = sum(row[1] for row in problem_stats_raw)
        problem_stats = []
        for row in problem_stats_raw:
            percentage = round((row[1] / total) * 100, 1) if total > 0 else 0
            problem_stats.append({
                "problem_type": row[0],
                "count": row[1],
                "percentage": percentage
            })
        
        conn.close()
        
        return jsonify({
            "total_requests": total_requests,
            "completed_requests": completed_requests,
            "in_process": in_process,
            "avg_days": avg_days,
            "status_distribution": status_distribution,
            "type_distribution": type_distribution,
            "problem_stats": problem_stats
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/masters')
def get_masters():
    """Получение списка мастеров"""
    try:
        conn = sqlite3.connect('service_requests.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT m.*, 
                   (SELECT COUNT(*) FROM service_requests sr 
                    WHERE sr.master_id = m.id AND sr.request_status = 'В процессе ремонта') as active_requests,
                   (SELECT COUNT(*) FROM service_requests sr 
                    WHERE sr.master_id = m.id) as total_requests,
                   (SELECT COUNT(*) FROM comments c 
                    WHERE c.master_id = m.id) as comment_count
            FROM masters m
            ORDER BY m.master_fio
        ''')
        rows = cursor.fetchall()
        conn.close()
        
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/comments')
def get_all_comments():
    """Получение всех комментариев"""
    try:
        conn = sqlite3.connect('service_requests.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT c.*, u.user_type 
            FROM comments c
            LEFT JOIN users u ON c.user_id = u.id
            ORDER BY c.created_at DESC
        ''')
        rows = cursor.fetchall()
        conn.close()
        
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        print(f"Ошибка при получении комментариев: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/comments/request/<int:request_id>')
def get_comments_by_request(request_id):
    """Получение комментариев для заявки"""
    try:
        conn = sqlite3.connect('service_requests.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT c.*, u.user_type 
            FROM comments c
            LEFT JOIN users u ON c.user_id = u.id
            WHERE c.request_id = ?
            ORDER BY c.created_at DESC
        ''', (request_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        print(f"Ошибка при получении комментариев для заявки {request_id}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/comments', methods=['POST'])
def add_comment():
    """Добавление комментария"""
    try:
        data = request.json
        
        if 'user_id' not in session:
            return jsonify({"success": False, "error": "Требуется авторизация"}), 401
        
        user_type = session.get('user_type')
        user_id = session.get('user_id')
        user_fio = session.get('user_name')
        
        conn = sqlite3.connect('service_requests.db')
        cursor = conn.cursor()
        
        # Получаем ID мастера, если комментарий от мастера
        master_id = None
        if user_type == 'master':
            cursor.execute("SELECT id FROM masters WHERE user_id = ?", (user_id,))
            master_result = cursor.fetchone()
            if master_result:
                master_id = master_result[0]
        
        # Добавляем комментарий
        cursor.execute('''
            INSERT INTO comments (request_id, master_id, user_id, user_fio, user_type, message)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (data['request_id'], master_id, user_id, user_fio, user_type, data['message']))
        
        # Обновляем флаг has_comment в заявке
        cursor.execute('''
            UPDATE service_requests 
            SET has_comment = 1 
            WHERE request_id = ?
        ''', (data['request_id'],))
        
        # Обновляем запчасти, если указаны
        if 'repair_parts' in data and data['repair_parts']:
            cursor.execute('''
                UPDATE service_requests 
                SET repair_parts = COALESCE(repair_parts || ', ', '') || ?
                WHERE request_id = ?
            ''', (data['repair_parts'], data['request_id']))
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True})
    except Exception as e:
        print(f"Ошибка при добавлении комментария: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/requests/search')
def search_requests():
    """Поиск заявок"""
    try:
        query = request.args.get('q', '')
        user_type = session.get('user_type')
        user_login = session.get('user_login')
        
        conn = sqlite3.connect('service_requests.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        search_pattern = f"%{query}%"
        
        if user_type == 'client':
            cursor.execute('''
                SELECT * FROM service_requests 
                WHERE client_login = ? AND (
                    request_id LIKE ? OR 
                    problem_description LIKE ? OR 
                    client_fio LIKE ? OR 
                    client_phone LIKE ? OR
                    tech_type LIKE ? OR
                    tech_model LIKE ?
                )
                ORDER BY start_date DESC
            ''', (user_login, search_pattern, search_pattern, search_pattern, search_pattern, search_pattern, search_pattern))
        elif user_type == 'master':
            cursor.execute("SELECT id FROM masters WHERE master_login = ?", (user_login,))
            master_result = cursor.fetchone()
            
            if master_result:
                master_id = master_result[0]
                cursor.execute('''
                    SELECT * FROM service_requests 
                    WHERE master_id = ? AND (
                        request_id LIKE ? OR 
                        problem_description LIKE ? OR 
                        client_fio LIKE ? OR 
                        client_phone LIKE ? OR
                        tech_type LIKE ? OR
                        tech_model LIKE ?
                    )
                    ORDER BY start_date DESC
                ''', (master_id, search_pattern, search_pattern, search_pattern, search_pattern, search_pattern, search_pattern))
            else:
                return jsonify([])
        else:
            cursor.execute('''
                SELECT * FROM service_requests 
                WHERE request_id LIKE ? OR 
                    problem_description LIKE ? OR 
                    client_fio LIKE ? OR 
                    client_phone LIKE ? OR
                    tech_type LIKE ? OR
                    tech_model LIKE ?
                ORDER BY start_date DESC
            ''', (search_pattern, search_pattern, search_pattern, search_pattern, search_pattern, search_pattern))
        
        rows = cursor.fetchall()
        conn.close()
        
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("="*60)
    print("Сервисный центр 'БытСервис' - Система учета заявок")
    print("Сервер доступен по адресу: http://localhost:8000")
    print("="*60)
    print("Функциональность:")
    print("   • Все пользователи из файла загружены в систему")
    print("   • Все комментарии из файла загружены и отображаются")
    print("   • Создание и управление заявками")
    print("   • Назначение мастеров")
    print("   • Добавление комментариев и запчастей")
    print("   • Статистика работы отдела обслуживания")
    print("   • Поиск заявок")
    print("   • Выбор готовых комментариев из файла")
    print("="*60)
    print("Все пользователи из файла:")
    print("   • Менеджер: kasoo / root")
    print("   • Мастер: murashov123 / qwerty")
    print("   • Мастер: test1 / test1")
    print("   • Оператор: perinaAD / 250519")
    print("   • Оператор: krutiha1234567 / 1234567890")
    print("   • Мастер: login1 / pass1")
    print("   • Заказчик: login2 / pass2")
    print("   • Заказчик: login3 / pass3")
    print("   • Заказчик: login4 / pass4")
    print("   • Мастер: login5 / pass5")
    print("="*60)
    print("Примечание:")
    print("   • В окне входа отображаются реальные пароли из файла")
    print("   • Можно кликнуть на учетную запись для автозаполнения")
    print("   • При выходе не показываются ошибки соединения")
    print("   • При добавлении комментария можно выбрать готовые шаблоны")
    print("="*60)
    app.run(debug=True, host='0.0.0.0', port=8000)