#!/usr/bin/env python3
# repair_system_sqlite_complete_adapted.py
# Полный рабочий код системы учета заявок для SQLite с поддержкой новых файлов

import sqlite3
import os
import sys
import json
import datetime
import shutil
import csv
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import hashlib
import argparse

# ============================================================================
# 1. КОНСТАНТЫ И НАСТРОЙКИ
# ============================================================================

class UserRole(Enum):
    MANAGER = "Менеджер"
    SPECIALIST = "Мастер"  # Изменено с "Специалист" на "Мастер"
    OPERATOR = "Оператор"
    CLIENT = "Заказчик"

class RequestStatus(Enum):
    NEW = "Новая заявка"
    CONFIRMED = "Подтверждена"
    DIAGNOSIS = "На диагностике"
    IN_PROGRESS = "В процессе ремонта"
    WAITING_PARTS = "Ожидает запчасти"
    READY = "Готова к выдаче"
    COMPLETED = "Выполнена"
    CANCELLED = "Отменена"

# ============================================================================
# 2. МОДЕЛИ ДАННЫХ
# ============================================================================

@dataclass
class User:
    user_id: int
    full_name: str
    phone: str
    login: str
    password_hash: str
    user_type_id: int
    is_active: bool
    created_at: str
    
    @property
    def role(self) -> str:
        roles = {
            1: UserRole.MANAGER.value,
            2: UserRole.SPECIALIST.value,
            3: UserRole.OPERATOR.value,
            4: UserRole.CLIENT.value
        }
        return roles.get(self.user_type_id, "Неизвестно")

@dataclass
class RepairRequest:
    request_id: int
    request_number: str
    start_date: str
    equipment_type: str
    equipment_model: str
    problem_description: str
    status: str
    client_name: str
    master_name: Optional[str]
    priority: int
    completion_date: Optional[str]

@dataclass
class Comment:
    comment_id: int
    message: str
    master_name: str
    request_id: int
    created_at: str

# ============================================================================
# 3. ОСНОВНОЙ КЛАСС ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ (АДАПТИРОВАННЫЙ)
# ============================================================================

class RepairSystemDatabase:
    """Класс для работы с базой данных системы учета заявок (адаптированный под новые файлы)"""
    
    def __init__(self, db_path: str = 'repair_management.db'):
        self.db_path = db_path
        self.conn = None
        self._ensure_directories()
        
    def _ensure_directories(self):
        """Создать необходимые директории"""
        os.makedirs('backups', exist_ok=True)
        os.makedirs('exports', exist_ok=True)
        os.makedirs('reports', exist_ok=True)
        os.makedirs('imports', exist_ok=True)
    
    def connect(self) -> sqlite3.Connection:
        """Установить соединение с базой данных"""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
        return self.conn
    
    def disconnect(self):
        """Закрыть соединение с базой данных"""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def initialize_database(self):
        """Инициализировать базу данных: создать таблицы и заполнить начальными данными"""
        print("🔄 Инициализация базы данных...")
        
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            # ============================================================
            # Создание таблиц (адаптировано под новые данные)
            # ============================================================
            
            # Таблица типов пользователей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_types (
                    user_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type_name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица пользователей (адаптировано под inputDataUsers.xlsx)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    login TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    user_type_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    FOREIGN KEY (user_type_id) REFERENCES user_types(user_type_id) ON DELETE RESTRICT
                )
            """)
            
            # Таблица типов оборудования (упрощена для новых данных)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS equipment_types (
                    equipment_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type_name TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица моделей оборудования (упрощена для новых данных)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS equipment_models (
                    equipment_model_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name TEXT NOT NULL,
                    equipment_type_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(model_name, equipment_type_id),
                    FOREIGN KEY (equipment_type_id) REFERENCES equipment_types(equipment_type_id) ON DELETE CASCADE
                )
            """)
            
            # Таблица статусов заявок
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS request_statuses (
                    status_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status_name TEXT NOT NULL UNIQUE,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица заявок (адаптировано под inputDataRequests.xlsx)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS repair_requests (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_number TEXT GENERATED ALWAYS AS ('REQ-' || printf('%06d', request_id)),
                    start_date DATE NOT NULL,
                    equipment_type_id INTEGER NOT NULL,
                    equipment_model_id INTEGER NOT NULL,
                    problem_description TEXT NOT NULL,
                    status_id INTEGER NOT NULL,
                    completion_date DATE,
                    repair_parts TEXT,
                    master_id INTEGER,
                    client_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    priority INTEGER DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
                    CHECK (completion_date IS NULL OR completion_date >= start_date),
                    FOREIGN KEY (equipment_type_id) REFERENCES equipment_types(equipment_type_id) ON DELETE RESTRICT,
                    FOREIGN KEY (equipment_model_id) REFERENCES equipment_models(equipment_model_id) ON DELETE RESTRICT,
                    FOREIGN KEY (status_id) REFERENCES request_statuses(status_id) ON DELETE RESTRICT,
                    FOREIGN KEY (master_id) REFERENCES users(user_id) ON DELETE SET NULL,
                    FOREIGN KEY (client_id) REFERENCES users(user_id) ON DELETE RESTRICT
                )
            """)
            
            # Таблица комментариев (адаптировано под inputDataComments.xlsx)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS comments (
                    comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    master_id INTEGER NOT NULL,
                    request_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (master_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (request_id) REFERENCES repair_requests(request_id) ON DELETE CASCADE
                )
            """)
            
            # ============================================================
            # Создание индексов
            # ============================================================
            
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_users_user_type ON users(user_type_id)",
                "CREATE INDEX IF NOT EXISTS idx_users_login ON users(login)",
                "CREATE INDEX IF NOT EXISTS idx_requests_status ON repair_requests(status_id)",
                "CREATE INDEX IF NOT EXISTS idx_requests_client ON repair_requests(client_id)",
                "CREATE INDEX IF NOT EXISTS idx_requests_master ON repair_requests(master_id)",
                "CREATE INDEX IF NOT EXISTS idx_requests_dates ON repair_requests(start_date, completion_date)",
                "CREATE INDEX IF NOT EXISTS idx_comments_request ON comments(request_id)",
                "CREATE INDEX IF NOT EXISTS idx_comments_master ON comments(master_id)"
            ]
            
            for index_sql in indexes:
                cursor.execute(index_sql)
            
            conn.commit()
            print("✅ Таблицы созданы успешно")
            
            # ============================================================
            # Заполнение начальными данными
            # ============================================================
            
            self._populate_initial_data(cursor)
            
            conn.commit()
            print("✅ Начальные данные загружены успешно")
            
            # ============================================================
            # Создание представлений
            # ============================================================
            
            self._create_views(cursor)
            conn.commit()
            print("✅ Представления созданы успешно")
            
            print(f"\n🎉 База данных инициализирована: {self.db_path}")
            print(f"📊 Статистика:")
            print(f"   👥 Пользователей: {self.get_users_count()}")
            print(f"   📋 Заявок: {self.get_requests_count()}")
            print(f"   💬 Комментариев: {self.get_comments_count()}")
            
        except Exception as e:
            print(f"❌ Ошибка при инициализации базы данных: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            self.disconnect()
    
    def _populate_initial_data(self, cursor):
        """Заполнить базу данных начальными данными"""
        
        # Типы пользователей
        user_types = [
            ('Менеджер', 'Управление системой, полный доступ'),
            ('Мастер', 'Выполнение ремонтных работ'),
            ('Оператор', 'Обработка заявок, назначение мастеров'),
            ('Заказчик', 'Создание заявок на ремонт')
        ]
        
        cursor.executemany(
            "INSERT OR IGNORE INTO user_types (type_name, description) VALUES (?, ?)",
            user_types
        )
        
        # Статусы заявок (из новых данных)
        request_statuses = [
            ('Новая заявка', 1),
            ('В процессе ремонта', 1),
            ('Готова к выдаче', 1),
            ('Выполнена', 1),
            ('Отменена', 1)
        ]
        
        cursor.executemany(
            "INSERT OR IGNORE INTO request_statuses (status_name, is_active) VALUES (?, ?)",
            request_statuses
        )
    
    def _create_views(self, cursor):
        """Создать представления (VIEWS)"""
        
        # Представление для заявок с полной информацией
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS vw_requests_full AS
            SELECT 
                rr.request_id,
                rr.request_number,
                rr.start_date,
                et.type_name AS equipment_type,
                em.model_name AS equipment_model,
                rr.problem_description,
                rs.status_name,
                uc.full_name AS client_name,
                uc.phone AS client_phone,
                um.full_name AS master_name,
                rr.completion_date,
                rr.repair_parts,
                rr.priority,
                CASE 
                    WHEN rr.completion_date IS NOT NULL THEN 
                        julianday(rr.completion_date) - julianday(rr.start_date)
                    ELSE 
                        julianday('now') - julianday(rr.start_date)
                END AS days_in_process,
                rr.created_at
            FROM repair_requests rr
            JOIN equipment_types et ON rr.equipment_type_id = et.equipment_type_id
            JOIN equipment_models em ON rr.equipment_model_id = em.equipment_model_id
            JOIN request_statuses rs ON rr.status_id = rs.status_id
            JOIN users uc ON rr.client_id = uc.user_id
            LEFT JOIN users um ON rr.master_id = um.user_id
            ORDER BY rr.priority, rr.start_date DESC
        """)
        
        # Представление статистики по мастерам
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS vw_masters_statistics AS
            SELECT 
                u.user_id,
                u.full_name AS master_name,
                ut.type_name AS user_type,
                COUNT(rr.request_id) AS total_requests,
                SUM(CASE WHEN rs.status_name = 'В процессе ремонта' THEN 1 ELSE 0 END) AS in_progress_count,
                SUM(CASE WHEN rs.status_name = 'Выполнена' THEN 1 ELSE 0 END) AS completed_count,
                SUM(CASE WHEN rs.status_name = 'Готова к выдаче' THEN 1 ELSE 0 END) AS ready_count,
                AVG(CASE 
                    WHEN rr.completion_date IS NOT NULL THEN 
                        julianday(rr.completion_date) - julianday(rr.start_date)
                    ELSE NULL 
                END) AS avg_completion_days
            FROM users u
            LEFT JOIN repair_requests rr ON u.user_id = rr.master_id
            LEFT JOIN request_statuses rs ON rr.status_id = rs.status_id
            JOIN user_types ut ON u.user_type_id = ut.user_type_id
            WHERE ut.type_name = 'Мастер'
            GROUP BY u.user_id, u.full_name, ut.type_name
            ORDER BY total_requests DESC
        """)
        
        # Представление для комментариев
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS vw_comments_full AS
            SELECT 
                c.comment_id,
                c.message,
                u.full_name AS master_name,
                c.request_id,
                rr.request_number,
                c.created_at
            FROM comments c
            JOIN users u ON c.master_id = u.user_id
            JOIN repair_requests rr ON c.request_id = rr.request_id
            ORDER BY c.created_at DESC
        """)
    
    # ============================================================================
    # 4. МЕТОДЫ ДЛЯ ИМПОРТА ДАННЫХ ИЗ EXCEL ФАЙЛОВ
    # ============================================================================
    
    def import_from_excel(self, users_file: str, requests_file: str, comments_file: str) -> Dict:
        """Импортировать данные из Excel файлов"""
        try:
            # Проверяем наличие библиотеки pandas
            try:
                import pandas as pd
            except ImportError:
                return {
                    'success': False,
                    'message': 'Для импорта из Excel необходимо установить библиотеку pandas: pip install pandas openpyxl'
                }
            
            conn = self.connect()
            cursor = conn.cursor()
            
            # Словари для сопоставления ID
            user_id_mapping = {}  # старый ID -> новый ID
            request_id_mapping = {}  # старый ID -> новый ID
            
            # ============================================================
            # 1. Импорт пользователей из inputDataUsers.xlsx
            # ============================================================
            print("📥 Импорт пользователей...")
            try:
                users_df = pd.read_excel(users_file)
                print(f"   Найдено пользователей: {len(users_df)}")
                
                # Сопоставление типов пользователей
                type_mapping = {
                    'Менеджер': 1,
                    'Мастер': 2,
                    'Оператор': 3,
                    'Заказчик': 4
                }
                
                for _, row in users_df.iterrows():
                    user_type_id = type_mapping.get(row['type'], 4)
                    password_hash = hashlib.sha256(str(row['password']).encode()).hexdigest()
                    
                    # Проверяем, существует ли пользователь с таким логином
                    cursor.execute(
                        "SELECT user_id FROM users WHERE login = ?",
                        (str(row['login']),)
                    )
                    existing_user = cursor.fetchone()
                    
                    if existing_user:
                        # Обновляем существующего пользователя
                        user_id = existing_user['user_id']
                        cursor.execute("""
                            UPDATE users SET 
                                full_name = ?,
                                phone = ?,
                                password_hash = ?,
                                user_type_id = ?,
                                is_active = 1
                            WHERE user_id = ?
                        """, (
                            str(row['fio']),
                            str(row['phone']),
                            password_hash,
                            user_type_id,
                            user_id
                        ))
                    else:
                        # Добавляем нового пользователя
                        cursor.execute("""
                            INSERT INTO users (full_name, phone, login, password_hash, user_type_id, is_active)
                            VALUES (?, ?, ?, ?, ?, 1)
                        """, (
                            str(row['fio']),
                            str(row['phone']),
                            str(row['login']),
                            password_hash,
                            user_type_id
                        ))
                        user_id = cursor.lastrowid
                    
                    user_id_mapping[int(row['userID'])] = user_id
                
                print(f"   ✅ Импортировано пользователей: {len(user_id_mapping)}")
                
            except Exception as e:
                conn.rollback()
                return {
                    'success': False,
                    'message': f'Ошибка при импорте пользователей: {str(e)}'
                }
            
            # ============================================================
            # 2. Импорт заявок из inputDataRequests.xlsx
            # ============================================================
            print("📥 Импорт заявок...")
            try:
                requests_df = pd.read_excel(requests_file)
                print(f"   Найдено заявок: {len(requests_df)}")
                
                # Сопоставление статусов заявок
                status_mapping = {
                    'Новая заявка': 1,
                    'В процессе ремонта': 2,
                    'Готова к выдаче': 3,
                    'Выполнена': 4,
                    'Отменена': 5
                }
                
                # Словарь для сопоставления типов и моделей оборудования
                equipment_types = {}
                equipment_models = {}
                
                for _, row in requests_df.iterrows():
                    # Получаем или создаем тип оборудования
                    equipment_type = str(row['homeTechType'])
                    if equipment_type not in equipment_types:
                        cursor.execute(
                            "SELECT equipment_type_id FROM equipment_types WHERE type_name = ?",
                            (equipment_type,)
                        )
                        result = cursor.fetchone()
                        
                        if result:
                            type_id = result['equipment_type_id']
                        else:
                            cursor.execute(
                                "INSERT INTO equipment_types (type_name) VALUES (?)",
                                (equipment_type,)
                            )
                            type_id = cursor.lastrowid
                        
                        equipment_types[equipment_type] = type_id
                    
                    type_id = equipment_types[equipment_type]
                    
                    # Получаем или создаем модель оборудования
                    equipment_model = str(row['homeTechModel'])
                    model_key = f"{equipment_type}_{equipment_model}"
                    
                    if model_key not in equipment_models:
                        cursor.execute(
                            """SELECT equipment_model_id FROM equipment_models 
                               WHERE model_name = ? AND equipment_type_id = ?""",
                            (equipment_model, type_id)
                        )
                        result = cursor.fetchone()
                        
                        if result:
                            model_id = result['equipment_model_id']
                        else:
                            cursor.execute(
                                """INSERT INTO equipment_models (model_name, equipment_type_id) 
                                   VALUES (?, ?)""",
                                (equipment_model, type_id)
                            )
                            model_id = cursor.lastrowid
                        
                        equipment_models[model_key] = model_id
                    
                    model_id = equipment_models[model_key]
                    
                    # Получаем статус
                    status_id = status_mapping.get(str(row['requestStatus']), 1)
                    
                    # Получаем клиента и мастера
                    client_id = user_id_mapping.get(int(row['clientID']))
                    master_id = user_id_mapping.get(int(row['masterID'])) if not pd.isna(row['masterID']) else None
                    
                    # Обрабатываем даты
                    start_date = row['startDate']
                    completion_date = row['completionDate'] if not pd.isna(row['completionDate']) else None
                    
                    # Обрабатываем repair_parts
                    repair_parts = str(row['repairParts']) if not pd.isna(row['repairParts']) else None
                    
                    # Вставляем заявку
                    cursor.execute("""
                        INSERT INTO repair_requests (
                            start_date, equipment_type_id, equipment_model_id, 
                            problem_description, status_id, completion_date,
                            repair_parts, master_id, client_id, priority
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        start_date, type_id, model_id, str(row['problemDescryption']),
                        status_id, completion_date, repair_parts, master_id, client_id, 3
                    ))
                    
                    request_id = cursor.lastrowid
                    request_id_mapping[int(row['requestID'])] = request_id
                
                print(f"   ✅ Импортировано заявок: {len(request_id_mapping)}")
                
            except Exception as e:
                conn.rollback()
                return {
                    'success': False,
                    'message': f'Ошибка при импорте заявок: {str(e)}'
                }
            
            # ============================================================
            # 3. Импорт комментариев из inputDataComments.xlsx
            # ============================================================
            print("📥 Импорт комментариев...")
            try:
                comments_df = pd.read_excel(comments_file)
                print(f"   Найдено комментариев: {len(comments_df)}")
                
                comment_count = 0
                for _, row in comments_df.iterrows():
                    master_id = user_id_mapping.get(int(row['masterID']))
                    request_id = request_id_mapping.get(int(row['requestID']))
                    
                    if master_id and request_id:
                        cursor.execute("""
                            INSERT INTO comments (message, master_id, request_id)
                            VALUES (?, ?, ?)
                        """, (str(row['message']), master_id, request_id))
                        comment_count += 1
                
                print(f"   ✅ Импортировано комментариев: {comment_count}")
                
            except Exception as e:
                conn.rollback()
                return {
                    'success': False,
                    'message': f'Ошибка при импорте комментариев: {str(e)}'
                }
            
            conn.commit()
            
            return {
                'success': True,
                'message': 'Данные успешно импортированы',
                'stats': {
                    'users': len(user_id_mapping),
                    'requests': len(request_id_mapping),
                    'comments': comment_count
                }
            }
            
        except Exception as e:
            if conn:
                conn.rollback()
            return {
                'success': False,
                'message': f'Ошибка при импорте данных: {str(e)}'
            }
        finally:
            self.disconnect()
    
    # ============================================================================
    # 5. ОСНОВНЫЕ МЕТОДЫ ДЛЯ РАБОТЫ С ДАННЫМИ
    # ============================================================================
    
    def authenticate_user(self, login: str, password: str) -> Optional[Dict]:
        """Аутентификация пользователя"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            cursor.execute("""
                SELECT u.*, ut.type_name as role 
                FROM users u
                JOIN user_types ut ON u.user_type_id = ut.user_type_id
                WHERE u.login = ? AND u.password_hash = ? AND u.is_active = 1
            """, (login, password_hash))
            
            user = cursor.fetchone()
            
            if user:
                # Обновляем время последнего входа
                cursor.execute(
                    "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (user['user_id'],)
                )
                conn.commit()
                
                return dict(user)
            
            return None
            
        except Exception as e:
            print(f"Ошибка аутентификации: {e}")
            return None
    
    def create_request(self, client_id: int, equipment_type: str, 
                      equipment_model: str, problem_description: str, 
                      priority: int = 3) -> Dict:
        """Создать новую заявку"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            # Получаем или создаем тип оборудования
            cursor.execute(
                "SELECT equipment_type_id FROM equipment_types WHERE type_name = ?",
                (equipment_type,)
            )
            type_result = cursor.fetchone()
            
            if type_result:
                type_id = type_result['equipment_type_id']
            else:
                cursor.execute(
                    "INSERT INTO equipment_types (type_name) VALUES (?)",
                    (equipment_type,)
                )
                type_id = cursor.lastrowid
            
            # Получаем или создаем модель оборудования
            cursor.execute(
                """SELECT equipment_model_id FROM equipment_models 
                   WHERE model_name = ? AND equipment_type_id = ?""",
                (equipment_model, type_id)
            )
            model_result = cursor.fetchone()
            
            if model_result:
                model_id = model_result['equipment_model_id']
            else:
                cursor.execute(
                    """INSERT INTO equipment_models (model_name, equipment_type_id) 
                       VALUES (?, ?)""",
                    (equipment_model, type_id)
                )
                model_id = cursor.lastrowid
            
            # Получаем статус "Новая заявка"
            cursor.execute(
                "SELECT status_id FROM request_statuses WHERE status_name = 'Новая заявка'"
            )
            status_id = cursor.fetchone()['status_id']
            
            cursor.execute("""
                INSERT INTO repair_requests 
                (start_date, equipment_type_id, equipment_model_id, 
                 problem_description, status_id, client_id, priority)
                VALUES (date('now'), ?, ?, ?, ?, ?, ?)
            """, (type_id, model_id, problem_description, status_id, client_id, priority))
            
            request_id = cursor.lastrowid
            
            # Генерируем номер заявки
            request_number = f"REQ-{request_id:06d}"
            cursor.execute(
                "UPDATE repair_requests SET request_number = ? WHERE request_id = ?",
                (request_number, request_id)
            )
            
            conn.commit()
            
            return {
                'success': True,
                'request_id': request_id,
                'request_number': request_number,
                'message': 'Заявка успешно создана'
            }
            
        except Exception as e:
            if conn:
                conn.rollback()
            return {
                'success': False,
                'message': f'Ошибка при создании заявки: {str(e)}'
            }
    
    def assign_master(self, request_id: int, master_id: int, user_id: int) -> Dict:
        """Назначить мастера на заявку"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            # Проверяем заявку
            cursor.execute(
                "SELECT status_id FROM repair_requests WHERE request_id = ?",
                (request_id,)
            )
            request = cursor.fetchone()
            
            if not request:
                return {'success': False, 'message': 'Заявка не найдена'}
            
            # Проверяем, является ли пользователь мастером
            cursor.execute("""
                SELECT 1 FROM users u 
                JOIN user_types ut ON u.user_type_id = ut.user_type_id
                WHERE u.user_id = ? AND ut.type_name IN ('Мастер', 'Менеджер')
            """, (master_id,))
            
            if not cursor.fetchone():
                return {'success': False, 'message': 'Пользователь не является мастером'}
            
            # Получаем статус "В процессе ремонта"
            cursor.execute(
                "SELECT status_id FROM request_statuses WHERE status_name = 'В процессе ремонта'"
            )
            new_status_id = cursor.fetchone()['status_id']
            
            # Обновляем заявку
            cursor.execute("""
                UPDATE repair_requests 
                SET master_id = ?, status_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE request_id = ?
            """, (master_id, new_status_id, request_id))
            
            # Добавляем комментарий
            cursor.execute("""
                INSERT INTO comments (message, master_id, request_id)
                VALUES ('Мастер назначен на заявку', ?, ?)
            """, (user_id, request_id))
            
            conn.commit()
            
            return {
                'success': True,
                'message': 'Мастер успешно назначен',
                'new_status': 'В процессе ремонта'
            }
            
        except Exception as e:
            if conn:
                conn.rollback()
            return {
                'success': False,
                'message': f'Ошибка при назначении мастера: {str(e)}'
            }
    
    def update_request_status(self, request_id: int, status_name: str, 
                            user_id: int) -> Dict:
        """Обновить статус заявки"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            # Получаем новый статус
            cursor.execute(
                "SELECT status_id FROM request_statuses WHERE status_name = ?",
                (status_name,)
            )
            result = cursor.fetchone()
            
            if not result:
                return {'success': False, 'message': 'Статус не найден'}
            
            new_status_id = result['status_id']
            
            # Обновляем заявку
            cursor.execute("""
                UPDATE repair_requests 
                SET status_id = ?, 
                    completion_date = CASE WHEN ? = 'Готова к выдаче' THEN date('now') ELSE completion_date END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE request_id = ?
            """, (new_status_id, status_name, request_id))
            
            conn.commit()
            
            return {
                'success': True,
                'message': f'Статус заявки обновлен на "{status_name}"'
            }
            
        except Exception as e:
            if conn:
                conn.rollback()
            return {
                'success': False,
                'message': f'Ошибка при обновлении статуса: {str(e)}'
            }
    
    def add_comment(self, request_id: int, master_id: int, message: str) -> Dict:
        """Добавить комментарий к заявке"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO comments (message, master_id, request_id)
                VALUES (?, ?, ?)
            """, (message, master_id, request_id))
            
            conn.commit()
            
            return {
                'success': True,
                'comment_id': cursor.lastrowid,
                'message': 'Комментарий добавлен'
            }
            
        except Exception as e:
            if conn:
                conn.rollback()
            return {
                'success': False,
                'message': f'Ошибка при добавлении комментария: {str(e)}'
            }
    
    # ============================================================================
    # 6. МЕТОДЫ ДЛЯ ПОЛУЧЕНИЯ ДАННЫХ
    # ============================================================================
    
    def get_all_requests(self, filters: Dict = None) -> List[Dict]:
        """Получить все заявки с фильтрацией"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            query = """
                SELECT * FROM vw_requests_full WHERE 1=1
            """
            params = []
            
            if filters:
                if filters.get('status'):
                    query += " AND status_name = ?"
                    params.append(filters['status'])
                
                if filters.get('client_id'):
                    query += " AND client_id = ?"
                    params.append(filters['client_id'])
                
                if filters.get('master_id'):
                    query += " AND master_id = ?"
                    params.append(filters['master_id'])
                
                if filters.get('start_date_from'):
                    query += " AND start_date >= ?"
                    params.append(filters['start_date_from'])
                
                if filters.get('start_date_to'):
                    query += " AND start_date <= ?"
                    params.append(filters['start_date_to'])
                
                if filters.get('equipment_type'):
                    query += " AND equipment_type = ?"
                    params.append(filters['equipment_type'])
            
            query += " ORDER BY priority, start_date DESC"
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Ошибка при получении заявок: {e}")
            return []
    
    def get_request_by_id(self, request_id: int) -> Optional[Dict]:
        """Получить заявку по ID"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT * FROM vw_requests_full WHERE request_id = ?",
                (request_id,)
            )
            
            row = cursor.fetchone()
            return dict(row) if row else None
            
        except Exception as e:
            print(f"Ошибка при получении заявки: {e}")
            return None
    
    def get_comments_for_request(self, request_id: int) -> List[Dict]:
        """Получить комментарии для заявки"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT c.*, u.full_name as master_name
                FROM comments c
                JOIN users u ON c.master_id = u.user_id
                WHERE c.request_id = ?
                ORDER BY c.created_at
            """, (request_id,))
            
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Ошибка при получении комментариев: {e}")
            return []
    
    def get_all_comments(self) -> List[Dict]:
        """Получить все комментарии"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM vw_comments_full")
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Ошибка при получении комментариев: {e}")
            return []
    
    def get_users_by_role(self, role_name: str) -> List[Dict]:
        """Получить пользователей по роли"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT u.*, ut.type_name as role 
                FROM users u
                JOIN user_types ut ON u.user_type_id = ut.user_type_id
                WHERE ut.type_name = ? AND u.is_active = 1
                ORDER BY u.full_name
            """, (role_name,))
            
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Ошибка при получении пользователей: {e}")
            return []
    
    def get_all_users(self) -> List[Dict]:
        """Получить всех пользователей"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT u.*, ut.type_name as role 
                FROM users u
                JOIN user_types ut ON u.user_type_id = ut.user_type_id
                WHERE u.is_active = 1
                ORDER BY ut.type_name, u.full_name
            """)
            
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Ошибка при получении пользователей: {e}")
            return []
    
    def get_masters_statistics(self) -> List[Dict]:
        """Получить статистику по мастерам"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM vw_masters_statistics")
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Ошибка при получении статистики мастеров: {e}")
            return []
    
    def get_requests_statistics(self, start_date: str = None, end_date: str = None) -> Dict:
        """Получить статистику по заявкам за период"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            if not start_date:
                start_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime('%Y-%m-%d')
            if not end_date:
                end_date = datetime.datetime.now().strftime('%Y-%m-%d')
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_requests,
                    SUM(CASE WHEN status_name = 'Новая заявка' THEN 1 ELSE 0 END) as new_requests,
                    SUM(CASE WHEN status_name = 'В процессе ремонта' THEN 1 ELSE 0 END) as in_progress,
                    SUM(CASE WHEN status_name = 'Готова к выдаче' THEN 1 ELSE 0 END) as ready,
                    SUM(CASE WHEN status_name = 'Выполнена' THEN 1 ELSE 0 END) as completed,
                    AVG(CASE WHEN completion_date IS NOT NULL 
                        THEN julianday(completion_date) - julianday(start_date) 
                        ELSE NULL END) as avg_completion_days
                FROM vw_requests_full
                WHERE start_date BETWEEN ? AND ?
            """, (start_date, end_date))
            
            result = cursor.fetchone()
            return dict(result) if result else {}
            
        except Exception as e:
            print(f"Ошибка при получении статистики: {e}")
            return {}
    
    def get_equipment_types(self) -> List[Dict]:
        """Получить типы оборудования"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM equipment_types ORDER BY type_name")
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Ошибка при получении типов оборудования: {e}")
            return []
    
    # ============================================================================
    # 7. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================================
    
    def get_users_count(self) -> int:
        """Получить количество пользователей"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0]
        except:
            return 0
    
    def get_requests_count(self) -> int:
        """Получить количество заявок"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM repair_requests")
            return cursor.fetchone()[0]
        except:
            return 0
    
    def get_comments_count(self) -> int:
        """Получить количество комментариев"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM comments")
            return cursor.fetchone()[0]
        except:
            return 0
    
    def get_database_info(self) -> Dict:
        """Получить информацию о базе данных"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            # Получаем список таблиц
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' 
                ORDER BY name
            """)
            tables = [row[0] for row in cursor.fetchall()]
            
            # Получаем размер базы данных
            db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
            
            return {
                'db_path': self.db_path,
                'db_size_bytes': db_size,
                'db_size_mb': round(db_size / (1024 * 1024), 2),
                'tables_count': len(tables),
                'tables': tables,
                'created_at': datetime.datetime.fromtimestamp(
                    os.path.getctime(self.db_path)
                ).strftime('%Y-%m-%d %H:%M:%S') if os.path.exists(self.db_path) else 'Не существует'
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    # ============================================================================
    # 8. МЕТОДЫ ДЛЯ РЕЗЕРВНОГО КОПИРОВАНИЯ И ЭКСПОРТА
    # ============================================================================
    
    def backup_database(self, backup_dir: str = 'backups') -> str:
        """Создать резервную копию базы данных"""
        try:
            if not os.path.exists(self.db_path):
                raise FileNotFoundError(f"База данных {self.db_path} не найдена")
            
            os.makedirs(backup_dir, exist_ok=True)
            
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"repair_db_backup_{timestamp}.db"
            backup_path = os.path.join(backup_dir, backup_filename)
            
            shutil.copy2(self.db_path, backup_path)
            
            return backup_path
            
        except Exception as e:
            print(f"Ошибка при создании резервной копии: {e}")
            return ""
    
    def export_to_json(self, export_path: str = None) -> str:
        """Экспортировать данные в JSON файл"""
        try:
            if not export_path:
                timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                export_path = f"exports/repair_data_export_{timestamp}.json"
            
            os.makedirs(os.path.dirname(export_path), exist_ok=True)
            
            data = {
                'export_info': {
                    'export_date': datetime.datetime.now().isoformat(),
                    'db_version': '1.0',
                    'exported_by': 'Repair System'
                },
                'users': self.get_all_users(),
                'requests': self.get_all_requests(),
                'comments': self.get_all_comments(),
                'equipment': self.get_equipment_types(),
                'statistics': {
                    'masters': self.get_masters_statistics(),
                    'requests': self.get_requests_statistics()
                }
            }
            
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            
            return export_path
            
        except Exception as e:
            print(f"Ошибка при экспорте в JSON: {e}")
            return ""
    
    def export_to_csv(self, export_path: str = None) -> str:
        """Экспортировать данные в CSV файл"""
        try:
            if not export_path:
                timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                export_path = f"exports/repair_requests_{timestamp}.csv"
            
            os.makedirs(os.path.dirname(export_path), exist_ok=True)
            
            requests = self.get_all_requests()
            
            if not requests:
                print("Нет данных для экспорта")
                return ""
            
            fieldnames = set()
            for request in requests:
                fieldnames.update(request.keys())
            
            fieldnames = sorted(fieldnames)
            
            with open(export_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(requests)
            
            return export_path
            
        except Exception as e:
            print(f"Ошибка при экспорте в CSV: {e}")
            return ""

# ============================================================================
# 9. КОМАНДНЫЙ ИНТЕРФЕЙС (CLI) С ДОБАВЛЕННЫМИ КОМАНДАМИ
# ============================================================================

def cli_menu():
    """Командный интерфейс для управления системой"""
    
    parser = argparse.ArgumentParser(
        description='Система учета заявок на ремонт оборудования (адаптированная под новые файлы)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  %(prog)s init                    # Инициализировать базу данных
  %(prog)s import                  # Импортировать данные из Excel файлов
  %(prog)s backup                  # Создать резервную копию
  %(prog)s export --format json    # Экспортировать данные в JSON
  %(prog)s report --daily          # Сформировать ежедневный отчет
  %(prog)s stats                   # Показать статистику
        """
    )
    
    parser.add_argument('command', help='Команда для выполнения')
    parser.add_argument('--db', default='repair_management.db', 
                       help='Путь к файлу базы данных')
    parser.add_argument('--format', choices=['json', 'csv'], default='json',
                       help='Формат экспорта данных')
    parser.add_argument('--users-file', default='inputDataUsers.xlsx',
                       help='Файл с данными пользователей')
    parser.add_argument('--requests-file', default='inputDataRequests.xlsx',
                       help='Файл с данными заявок')
    parser.add_argument('--comments-file', default='inputDataComments.xlsx',
                       help='Файл с данными комментариев')
    
    args = parser.parse_args()
    
    db = RepairSystemDatabase(args.db)
    
    if args.command == 'init':
        if os.path.exists(args.db):
            print(f"⚠️ База данных {args.db} уже существует")
            response = input("Пересоздать? (y/N): ")
            if response.lower() != 'y':
                return
        
        db.initialize_database()
        
    elif args.command == 'import':
        print("📥 Импорт данных из Excel файлов...")
        
        # Проверяем существование файлов
        files = {
            'Пользователи': args.users_file,
            'Заявки': args.requests_file,
            'Комментарии': args.comments_file
        }
        
        missing_files = []
        for file_type, file_path in files.items():
            if not os.path.exists(file_path):
                missing_files.append(f"{file_type}: {file_path}")
        
        if missing_files:
            print("❌ Не найдены файлы:")
            for missing in missing_files:
                print(f"   - {missing}")
            return
        
        result = db.import_from_excel(
            args.users_file,
            args.requests_file,
            args.comments_file
        )
        
        if result['success']:
            print("✅ Импорт выполнен успешно!")
            stats = result['stats']
            print(f"📊 Статистика импорта:")
            print(f"   👥 Пользователей: {stats['users']}")
            print(f"   📋 Заявок: {stats['requests']}")
            print(f"   💬 Комментариев: {stats['comments']}")
        else:
            print(f"❌ Ошибка при импорте: {result['message']}")
    
    elif args.command == 'backup':
        backup_path = db.backup_database()
        if backup_path:
            print(f"✅ Резервная копия создана: {backup_path}")
        else:
            print("❌ Ошибка при создании резервной копии")
    
    elif args.command == 'export':
        if args.format == 'json':
            export_path = db.export_to_json()
        else:  # csv
            export_path = db.export_to_csv()
        
        if export_path:
            print(f"✅ Данные экспортированы в: {export_path}")
        else:
            print("❌ Ошибка при экспорте данных")
    
    elif args.command == 'stats':
        info = db.get_database_info()
        
        print("\n📊 ИНФОРМАЦИЯ О БАЗЕ ДАННЫХ")
        print("=" * 50)
        print(f"Файл БД: {info.get('db_path', 'Неизвестно')}")
        print(f"Размер: {info.get('db_size_mb', 0)} MB")
        print(f"Создана: {info.get('created_at', 'Неизвестно')}")
        print(f"Таблиц: {info.get('tables_count', 0)}")
        
        print("\n📈 СТАТИСТИКА СИСТЕМЫ")
        print("=" * 50)
        print(f"Пользователей: {db.get_users_count()}")
        print(f"Заявок: {db.get_requests_count()}")
        print(f"Комментариев: {db.get_comments_count()}")
        
        # Статистика по статусам заявок
        requests = db.get_all_requests()
        if requests:
            status_counts = {}
            for req in requests:
                status = req.get('status_name', 'Неизвестно')
                status_counts[status] = status_counts.get(status, 0) + 1
            
            print("\n📋 ЗАЯВКИ ПО СТАТУСАМ:")
            for status, count in sorted(status_counts.items()):
                print(f"  {status}: {count}")
        
        # Статистика по типам оборудования
        equipment_types = db.get_equipment_types()
        if equipment_types:
            print("\n🔧 ТИПЫ ОБОРУДОВАНИЯ:")
            for eq_type in equipment_types:
                print(f"  • {eq_type.get('type_name', '')}")
    
    elif args.command == 'list':
        # Показать список заявок
        requests = db.get_all_requests()
        
        print("\n📋 СПИСОК ЗАЯВОК")
        print("=" * 100)
        print(f"{'Номер':<12} {'Дата':<12} {'Оборудование':<30} {'Статус':<20} {'Клиент':<20}")
        print("-" * 100)
        
        for req in requests[:20]:  # Показать первые 20
            equipment = f"{req.get('equipment_type', '')} - {req.get('equipment_model', '')}"
            print(f"{req.get('request_number', ''):<12} "
                  f"{req.get('start_date', ''):<12} "
                  f"{equipment:<30.30} "
                  f"{req.get('status_name', ''):<20.20} "
                  f"{req.get('client_name', ''):<20.20}")
        
        if len(requests) > 20:
            print(f"\n... и еще {len(requests) - 20} заявок")
    
    elif args.command == 'list-comments':
        # Показать список комментариев
        comments = db.get_all_comments()
        
        print("\n💬 СПИСОК КОММЕНТАРИЕВ")
        print("=" * 80)
        print(f"{'ID':<6} {'Заявка':<12} {'Мастер':<20} {'Сообщение':<30}")
        print("-" * 80)
        
        for comment in comments[:20]:
            print(f"{comment.get('comment_id', ''):<6} "
                  f"{comment.get('request_number', ''):<12} "
                  f"{comment.get('master_name', ''):<20.20} "
                  f"{comment.get('message', ''):<30.30}")
        
        if len(comments) > 20:
            print(f"\n... и еще {len(comments) - 20} комментариев")
    
    elif args.command == 'list-users':
        # Показать список пользователей
        users = db.get_all_users()
        
        print("\n👥 СПИСОК ПОЛЬЗОВАТЕЛЕЙ")
        print("=" * 70)
        print(f"{'ID':<6} {'ФИО':<30} {'Роль':<15} {'Логин':<15}")
        print("-" * 70)
        
        for user in users:
            print(f"{user.get('user_id', ''):<6} "
                  f"{user.get('full_name', ''):<30.30} "
                  f"{user.get('role', ''):<15} "
                  f"{user.get('login', ''):<15}")
        
        print(f"\nВсего пользователей: {len(users)}")
    
    else:
        print(f"❌ Неизвестная команда: {args.command}")
        parser.print_help()

# ============================================================================
# 10. ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================

def main():
    """Главная функция программы"""
    
    print("\n" + "="*60)
    print("🔧 СИСТЕМА УЧЕТА ЗАЯВОК НА РЕМОНТ ОБОРУДОВАНИЯ (АДАПТИРОВАННАЯ)")
    print("="*60)
    
    if len(sys.argv) > 1:
        # Если есть аргументы командной строки, используем CLI
        cli_menu()
    else:
        # Иначе показываем интерактивное меню
        db = RepairSystemDatabase('repair_management.db')
        
        while True:
            print("\n" + "="*60)
            print("ГЛАВНОЕ МЕНЮ")
            print("="*60)
            print("1. 🚀 Инициализировать базу данных")
            print("2. 📥 Импорт данных из Excel файлов")
            print("3. 📊 Показать статистику системы")
            print("4. 📋 Список заявок")
            print("5. 💬 Список комментариев")
            print("6. 👥 Список пользователей")
            print("7. 💾 Создать резервную копию")
            print("8. 📤 Экспорт данных")
            print("0. ❌ Выход")
            print("="*60)
            
            choice = input("\nВыберите действие (0-8): ").strip()
            
            if choice == '0':
                print("\n👋 До свидания!")
                break
            
            elif choice == '1':
                if os.path.exists('repair_management.db'):
                    print(f"⚠️ База данных уже существует")
                    response = input("Пересоздать? (y/N): ")
                    if response.lower() != 'y':
                        continue
                
                db.initialize_database()
                input("\nНажмите Enter для продолжения...")
                
            elif choice == '2':
                print("\n📥 ИМПОРТ ДАННЫХ ИЗ EXCEL ФАЙЛОВ")
                print("-" * 40)
                
                # Запрашиваем пути к файлам
                users_file = input("Файл пользователей [inputDataUsers.xlsx]: ").strip()
                requests_file = input("Файл заявок [inputDataRequests.xlsx]: ").strip()
                comments_file = input("Файл комментариев [inputDataComments.xlsx]: ").strip()
                
                if not users_file:
                    users_file = 'inputDataUsers.xlsx'
                if not requests_file:
                    requests_file = 'inputDataRequests.xlsx'
                if not comments_file:
                    comments_file = 'inputDataComments.xlsx'
                
                # Проверяем существование файлов
                files = [
                    (users_file, 'Пользователи'),
                    (requests_file, 'Заявки'),
                    (comments_file, 'Комментарии')
                ]
                
                missing_files = []
                for file_path, file_type in files:
                    if not os.path.exists(file_path):
                        missing_files.append(f"{file_type}: {file_path}")
                
                if missing_files:
                    print("\n❌ Не найдены файлы:")
                    for missing in missing_files:
                        print(f"   - {missing}")
                    input("\nНажмите Enter для продолжения...")
                    continue
                
                result = db.import_from_excel(users_file, requests_file, comments_file)
                
                if result['success']:
                    print("\n✅ Импорт выполнен успешно!")
                    stats = result['stats']
                    print(f"📊 Статистика импорта:")
                    print(f"   👥 Пользователей: {stats['users']}")
                    print(f"   📋 Заявок: {stats['requests']}")
                    print(f"   💬 Комментариев: {stats['comments']}")
                else:
                    print(f"\n❌ Ошибка при импорте: {result['message']}")
                
                input("\nНажмите Enter для продолжения...")
                
            elif choice == '3':
                info = db.get_database_info()
                
                print("\n📊 ИНФОРМАЦИЯ О БАЗЕ ДАННЫХ")
                print("-" * 40)
                for key, value in info.items():
                    if key != 'tables':
                        print(f"{key.replace('_', ' ').title()}: {value}")
                
                if 'tables' in info:
                    print(f"\nТаблицы ({len(info['tables'])}):")
                    for table in info['tables']:
                        print(f"  • {table}")
                
                print("\n📈 СТАТИСТИКА СИСТЕМЫ")
                print("-" * 40)
                print(f"Пользователей: {db.get_users_count()}")
                print(f"Заявок: {db.get_requests_count()}")
                print(f"Комментариев: {db.get_comments_count()}")
                
                input("\nНажмите Enter для продолжения...")
                
            elif choice == '4':
                requests = db.get_all_requests()
                
                print(f"\n📋 НАЙДЕНО ЗАЯВОК: {len(requests)}")
                print("="*100)
                print(f"{'Номер':<12} {'Дата':<12} {'Оборудование':<30} {'Статус':<20} {'Приоритет':<10}")
                print("-"*100)
                
                for req in requests[:50]:
                    equipment = f"{req.get('equipment_type', '')} - {req.get('equipment_model', '')}"
                    priority_map = {
                        1: 'Крит.', 2: 'Высок.', 3: 'Сред.', 4: 'Низк.', 5: 'Мин.'
                    }
                    priority_text = priority_map.get(req.get('priority', 3), 'Сред.')
                    
                    print(f"{req.get('request_number', ''):<12} "
                          f"{req.get('start_date', ''):<12} "
                          f"{equipment:<30.30} "
                          f"{req.get('status_name', ''):<20.20} "
                          f"{priority_text:<10}")
                
                if len(requests) > 50:
                    print(f"\n... и еще {len(requests) - 50} заявок")
                
                input("\nНажмите Enter для продолжения...")
                
            elif choice == '5':
                comments = db.get_all_comments()
                
                print(f"\n💬 НАЙДЕНО КОММЕНТАРИЕВ: {len(comments)}")
                print("="*80)
                print(f"{'ID':<6} {'Заявка':<12} {'Мастер':<20} {'Сообщение':<30} {'Дата':<12}")
                print("-"*80)
                
                for comment in comments[:30]:
                    created_date = comment.get('created_at', '')
                    if created_date:
                        created_date = created_date[:10]
                    
                    print(f"{comment.get('comment_id', ''):<6} "
                          f"{comment.get('request_number', ''):<12} "
                          f"{comment.get('master_name', ''):<20.20} "
                          f"{comment.get('message', ''):<30.30} "
                          f"{created_date:<12}")
                
                if len(comments) > 30:
                    print(f"\n... и еще {len(comments) - 30} комментариев")
                
                input("\nНажмите Enter для продолжения...")
                
            elif choice == '6':
                users = db.get_all_users()
                
                print(f"\n👥 НАЙДЕНО ПОЛЬЗОВАТЕЛЕЙ: {len(users)}")
                print("="*70)
                print(f"{'ID':<6} {'ФИО':<30} {'Роль':<15} {'Телефон':<12}")
                print("-"*70)
                
                for user in users:
                    print(f"{user.get('user_id', ''):<6} "
                          f"{user.get('full_name', ''):<30.30} "
                          f"{user.get('role', ''):<15} "
                          f"{user.get('phone', ''):<12}")
                
                input("\nНажмите Enter для продолжения...")
                
            elif choice == '7':
                backup_path = db.backup_database()
                
                if backup_path:
                    print(f"\n✅ Резервная копия создана: {backup_path}")
                    
                    if os.path.exists(backup_path):
                        size_mb = os.path.getsize(backup_path) / (1024 * 1024)
                        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(backup_path))
                        print(f"   Размер: {size_mb:.2f} MB")
                        print(f"   Дата создания: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    print("\n❌ Ошибка при создании резервной копии")
                
                input("\nНажмите Enter для продолжения...")
                
            elif choice == '8':
                print("\n📤 ВЫБЕРИТЕ ФОРМАТ ЭКСПОРТА:")
                print("1. JSON (рекомендуется)")
                print("2. CSV (для Excel)")
                
                format_choice = input("Ваш выбор (1-2): ").strip()
                
                if format_choice == '1':
                    export_path = db.export_to_json()
                    format_name = "JSON"
                elif format_choice == '2':
                    export_path = db.export_to_csv()
                    format_name = "CSV"
                else:
                    print("❌ Неверный выбор")
                    continue
                
                if export_path:
                    print(f"\n✅ Данные экспортированы в {format_name}: {export_path}")
                    
                    if os.path.exists(export_path):
                        size_kb = os.path.getsize(export_path) / 1024
                        print(f"   Размер файла: {size_kb:.2f} KB")
                else:
                    print("\n❌ Ошибка при экспорте данных")
                
                input("\nНажмите Enter для продолжения...")
                
            else:
                print("\n❌ Неверный выбор. Попробуйте еще раз.")
                input("\nНажмите Enter для продолжения...")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Программа прервана пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)