"""安全工具测试 - API 层"""

def test_validate_username():
    from app.utils.security import validate_username
    valid, msg = validate_username("user123")
    assert valid == True
    
    valid, msg = validate_username("ab")
    assert valid == False

def test_validate_password():
    from app.utils.security import validate_password
    valid, msg = validate_password("123456")
    assert valid == True

def test_sanitize_input():
    from app.utils.security import sanitize_input
    result = sanitize_input("<script>alert('xss')</script>")
    assert "<script>" not in result

def test_mask_sensitive_data():
    from app.utils.security import mask_sensitive_data
    data = {"password": "secret123", "username": "test"}
    masked = mask_sensitive_data(data)
    assert masked["password"] != "secret123"

def test_generate_request_id():
    from app.utils.security import generate_request_id
    id1 = generate_request_id()
    id2 = generate_request_id()
    assert id1 != id2
    assert len(id1) > 10
