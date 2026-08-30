"""
Test suite untuk memverifikasi perbaikan keamanan ALFA Sovereign AI.
Jalankan: python3 test_security_fixes.py
"""

import os
import sys
import tempfile
import sqlite3

sys.path.insert(0, '/workspace')

def test_dashboard_auth_requirement():
    """Test 1: Dashboard menolak start tanpa token saat binding ke 0.0.0.0"""
    print("\n[TEST 1] Dashboard auth requirement...")
    
    orig_token = os.environ.get('DASHBOARD_AUTH_TOKEN', '')
    orig_host = os.environ.get('DASHBOARD_HOST', '')
    
    try:
        os.environ['DASHBOARD_AUTH_TOKEN'] = ''
        os.environ['DASHBOARD_HOST'] = '0.0.0.0'
        
        import importlib
        import web_dashboard
        try:
            importlib.reload(web_dashboard)
            print("  FAIL: Seharusnya raise RuntimeError")
            return False
        except RuntimeError as e:
            if "tanpa autentikasi" in str(e).lower():
                print("  PASS: RuntimeError raised dengan pesan yang tepat")
            else:
                print(f"  FAIL: Pesan error tidak sesuai: {e}")
                return False
        
        os.environ['DASHBOARD_AUTH_TOKEN'] = 'testtoken123'
        os.environ['DASHBOARD_HOST'] = '0.0.0.0'
        importlib.reload(web_dashboard)
        print("  PASS: Dashboard start OK dengan token")
        
        os.environ['DASHBOARD_AUTH_TOKEN'] = ''
        os.environ['DASHBOARD_HOST'] = '127.0.0.1'
        importlib.reload(web_dashboard)
        print("  PASS: Dashboard start OK di localhost (dengan warning)")
        
        return True
        
    finally:
        if orig_token:
            os.environ['DASHBOARD_AUTH_TOKEN'] = orig_token
        elif 'DASHBOARD_AUTH_TOKEN' in os.environ:
            del os.environ['DASHBOARD_AUTH_TOKEN']
            
        if orig_host:
            os.environ['DASHBOARD_HOST'] = orig_host
        elif 'DASHBOARD_HOST' in os.environ:
            del os.environ['DASHBOARD_HOST']


def test_sql_column_whitelist():
    """Test 2: SQL UPDATE column whitelist mencegah injection"""
    print("\n[TEST 2] SQL column whitelist...")
    
    from database import update_custom_agent_sync
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        tmp_db = tmp.name
    
    try:
        conn = sqlite3.connect(tmp_db)
        conn.execute("""
            CREATE TABLE custom_agents (
                id INTEGER PRIMARY KEY,
                name TEXT, role TEXT, persona TEXT,
                system_instruction TEXT, provider TEXT, model TEXT,
                api_key_id INTEGER, avatar_emoji TEXT, color_theme TEXT,
                is_enabled INTEGER DEFAULT 1, enable_tools INTEGER DEFAULT 1
            )
        """)
        conn.execute("INSERT INTO custom_agents (id, name, role) VALUES (1, 'Test Agent', 'assistant')")
        conn.commit()
        conn.close()
        
        import database
        original_path = database.DB_PATH
        database.DB_PATH = tmp_db
        
        try:
            result = update_custom_agent_sync(1, {"name": "New Name", "role": "coder"})
            if result.get("status") == "success":
                print("  PASS: Update kolom valid berhasil")
            else:
                print(f"  FAIL: Update kolom valid gagal: {result}")
                return False
            
            malicious_key = "name; DROP TABLE custom_agents; --"
            result = update_custom_agent_sync(1, {malicious_key: "hacked"})
            if result.get("status") == "error" and "No valid fields" in result.get("message", ""):
                print("  PASS: Kolom berbahaya ditolak")
            else:
                print(f"  WARNING: Kolom berbahaya mungkin diproses: {result}")
            
            result = update_custom_agent_sync(1, {"name; DELETE FROM": "bad"})
            if result.get("status") == "error":
                print("  PASS: Kolom dengan karakter spesial ditolak")
            else:
                print(f"  FAIL: Kolom dengan karakter spesial diterima: {result}")
                return False
            
            conn = sqlite3.connect(tmp_db)
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_agents'")
            if cursor.fetchone():
                print("  PASS: Tabel custom_agents masih ada (tidak ter-inject)")
            else:
                print("  FAIL: Tabel custom_agents hilang!")
                return False
            conn.close()
            
            return True
            
        finally:
            database.DB_PATH = original_path
            
    finally:
        os.unlink(tmp_db)


def test_env_documentation():
    """Test 3: Dokumentasi .env.example sudah diperbaiki"""
    print("\n[TEST 3] Dokumentasi .env.example...")
    
    with open('/workspace/.env.example', 'r') as f:
        content = f.read()
    
    checks = [
        ("WAJIB diisi di production", "Warning production untuk DASHBOARD_AUTH_TOKEN"),
        ("TANPA autentikasi", "Penjelasan risiko tanpa token"),
        ("Minimal 16 karakter", "Rekomendasi panjang password"),
        ("openssl rand -base64 32", "Contoh generate token aman"),
    ]
    
    all_pass = True
    for check_str, description in checks:
        if check_str in content:
            print(f"  PASS: {description}")
        else:
            print(f"  FAIL: {description} - teks '{check_str}' tidak ditemukan")
            all_pass = False
    
    return all_pass


def run_all_tests():
    """Jalankan semua test security fixes"""
    print("=" * 60)
    print("ALFA SOVEREIGN AI - SECURITY FIXES VERIFICATION")
    print("=" * 60)
    
    tests = [
        test_dashboard_auth_requirement,
        test_sql_column_whitelist,
        test_env_documentation,
    ]
    
    results = []
    for test_fn in tests:
        try:
            result = test_fn()
            results.append((test_fn.__name__, result))
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            results.append((test_fn.__name__, False))
    
    print("\n" + "=" * 60)
    print("RINGKASAN HASIL:")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {name}")
    
    print(f"\nTotal: {passed}/{total} test passed")
    
    if passed == total:
        print("\nSEMUA TEST PASSED! Perbaikan keamanan berhasil diverifikasi.")
        return 0
    else:
        print(f"\n{total - passed} test gagal. Perlu review.")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
