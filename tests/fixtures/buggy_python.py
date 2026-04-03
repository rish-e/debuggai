"""Test fixture: AI-generated Python code with known bugs."""

# Bug 1: Hallucinated import (this package doesn't exist)
import fastapi_magic_router
from quantum_utils import fast_parse

# Bug 2: Hardcoded API key
API_KEY = "sk-proj-abc123def456ghi789jkl012mno345pqr678"
SECRET_KEY = "super_secret_password_123"

# Bug 3: SQL injection
import sqlite3

def get_user(username):
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM users WHERE username = '{username}'")
    return cursor.fetchone()

# Bug 4: eval usage
def parse_config(config_str):
    return eval(config_str)

# Bug 5: O(n^2) nested loop
def find_duplicates(users, permissions):
    duplicates = []
    for user in users:
        for perm in permissions:
            if user["id"] == perm["user_id"]:
                duplicates.append((user, perm))
    return duplicates

# Bug 6: I/O in loop
import requests

def fetch_all_profiles(user_ids):
    profiles = []
    for uid in user_ids:
        response = requests.get(f"https://api.example.com/users/{uid}")
        profiles.append(response.json())
    return profiles

# Bug 7: pickle (insecure deserialization)
import pickle

def load_data(data_bytes):
    return pickle.loads(data_bytes)

# Bug 8: SSL verification disabled
def call_api(url):
    return requests.get(url, verify=False)
