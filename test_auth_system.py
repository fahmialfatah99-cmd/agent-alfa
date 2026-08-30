"""Test sistem autentikasi dashboard."""
import sys
sys.path.insert(0, '/workspace')

# Reload untuk pastikan SESSION_SECRET konsisten
import importlib
import web_dashboard
importlib.reload(web_dashboard)

from web_dashboard import (
    create_user, authenticate_user, _create_session_token,
    validate_session, invalidate_session, get_all_users, delete_user,
    _hash_password, _verify_password, store_session
)

print("=" * 60)
print("TEST SISTEM AUTENTIKASI DASHBOARD")
print("=" * 60)

# Test 1: Hash password
print("\n[TEST 1] Hash Password")
pwd_hash, salt = _hash_password("testpassword123")
print(f"  Password hash: {pwd_hash[:20]}...")
print(f"  Salt: {salt}")
assert len(pwd_hash) == 64, "Hash harus 64 karakter (SHA256 hex)"
assert len(salt) == 32, "Salt harus 32 karakter"
print("  ✓ PASS")

# Test 2: Verify password
print("\n[TEST 2] Verify Password")
assert _verify_password("testpassword123", pwd_hash, salt), "Password harus match"
assert not _verify_password("wrongpassword", pwd_hash, salt), "Password salah harus reject"
print("  ✓ PASS")

# Test 3: Create user
print("\n[TEST 3] Create User")
try:
    user1 = create_user("admin_test", "admin123456", is_admin=True)
    print(f"  User created: {user1}")
    assert user1["user_id"] > 0
    assert user1["username"] == "admin_test"
    assert user1["is_admin"] == True
    print("  ✓ PASS")
except Exception as e:
    if "sudah terdaftar" in str(e):
        print(f"  ⚠ User sudah ada (normal jika test berulang)")
    else:
        raise

# Test 4: Authenticate user
print("\n[TEST 4] Authenticate User")
auth_result = authenticate_user("admin_test", "admin123456")
print(f"  Auth result: {auth_result}")
assert auth_result is not None, "Login harus berhasil"
assert auth_result["username"] == "admin_test"
assert auth_result["is_admin"] == True
print("  ✓ PASS")

# Test 5: Wrong password
print("\n[TEST 5] Wrong Password Rejection")
auth_fail = authenticate_user("admin_test", "wrongpassword")
assert auth_fail is None, "Login dengan password salah harus gagal"
print("  ✓ PASS - Password salah ditolak")

# Test 6: Create session token
print("\n[TEST 6] Create Session Token")
token = _create_session_token(auth_result["user_id"], auth_result["username"])
print(f"  Session token: {token[:50]}...")
assert "|||" in token, "Token harus format pipe-separated"
print("  ✓ PASS")

# Test 7: Store and validate session
print("\n[TEST 7] Store and Validate Session")
store_session(auth_result["user_id"], token)
validated = validate_session(token)
print(f"  Validated user: {validated}")
assert validated is not None, "Session harus valid"
assert validated["username"] == "admin_test"
print("  ✓ PASS")

# Test 8: Invalidate session (logout)
print("\n[TEST 8] Invalidate Session (Logout)")
invalidate_result = invalidate_session(token)
print(f"  Invalidate result: {invalidate_result}")
assert invalidate_result == True, "Session harus di-invalidate"

# Verify session is now invalid
revalidated = validate_session(token)
assert revalidated is None, "Session setelah logout harus invalid"
print("  ✓ PASS - Session berhasil di-logout")

# Test 9: Get all users
print("\n[TEST 9] Get All Users")
users = get_all_users()
print(f"  Total users: {len(users)}")
for u in users:
    print(f"    - {u['username']} (admin={u['is_admin']})")
assert len(users) >= 1, "Harus ada minimal 1 user"
print("  ✓ PASS")

print("\n" + "=" * 60)
print("SEMUA TEST PASSED! ✓")
print("=" * 60)
