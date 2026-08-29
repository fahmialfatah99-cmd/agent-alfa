"""Tests for ALFA Agent tools modules."""

import pytest
from unittest.mock import patch, MagicMock


class TestSystemTools:
    """Tests for system_tools module."""
    
    def test_get_system_stats_structure(self):
        """Test that get_system_stats returns proper structure."""
        from tools_modules.system_tools import get_system_stats
        
        with patch('tools_modules.system_tools.psutil') as mock_psutil:
            mock_psutil.cpu_percent.return_value = 25.0
            mock_psutil.cpu_count.return_value = 8
            mock_psutil.cpu_freq.return_value = MagicMock(current=2400)
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=17179869184,
                used=8589934592,
                available=8589934592,
                percent=50.0
            )
            mock_psutil.swap_memory.return_value = MagicMock(
                total=4294967296,
                used=1073741824
            )
            mock_psutil.disk_usage.return_value = MagicMock(
                total=536870912000,
                used=268435456000,
                percent=50.0
            )
            mock_psutil.boot_time.return_value = 1234567890
            mock_psutil.net_if_addrs.return_value = {}
            mock_psutil.sensors_battery.return_value = None
            mock_psutil.process_iter.return_value = []
            
            result = get_system_stats()
            
            assert result['status'] == 'success'
            assert 'cpu' in result
            assert 'ram' in result
            assert 'disk' in result
    
    def test_bash_blocked_reason_dangerous(self):
        """Test that dangerous commands are blocked."""
        from tools_modules.system_tools import _bash_blocked_reason
        
        dangerous_commands = [
            "rm -rf /",
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sda1",
            "chmod -R 777 /",
            "shutdown now"
        ]
        
        for cmd in dangerous_commands:
            reason = _bash_blocked_reason(cmd)
            assert reason is not None, f"Command should be blocked: {cmd}"


class TestWebTools:
    """Tests for web_tools module."""
    
    def test_web_search_error_handling(self):
        """Test web search error handling."""
        from tools_modules.web_tools import web_search
        
        with patch('tools_modules.web_tools.DDGS') as mock_ddgs:
            mock_ddgs.side_effect = Exception("Network error")
            
            result = web_search("test query")
            
            assert result['status'] == 'error'
            assert 'error' in result
    
    def test_fetch_web_page_content_success(self):
        """Test fetching web page content."""
        from tools_modules.web_tools import fetch_web_page_content
        
        with patch('tools_modules.web_tools.httpx') as mock_httpx:
            mock_response = MagicMock()
            mock_response.text = "<html><body>Test content</body></html>"
            mock_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_response
            
            with patch('tools_modules.web_tools.BeautifulSoup') as mock_bs:
                mock_bs.return_value.get_text.return_value = "Test content"
                
                result = fetch_web_page_content("https://example.com")
                
                assert result['status'] == 'success'


class TestFileTools:
    """Tests for file_tools module."""
    
    def test_read_local_file_not_found(self):
        """Test reading non-existent file."""
        from tools_modules.file_tools import read_local_file
        
        result = read_local_file("/nonexistent/file.txt")
        
        assert result['status'] == 'error'
        assert 'not found' in result.get('message', '').lower() or 'error' in result


class TestMemoryTools:
    """Tests for memory_tools module."""
    
    def test_save_knowledge_memory_structure(self):
        """Test saving knowledge memory returns proper structure."""
        from tools_modules.memory_tools import save_knowledge_memory
        
        # This will fail without DB but tests the structure
        result = save_knowledge_memory("test_topic", "test content")
        
        assert isinstance(result, dict)
        assert 'status' in result


class TestBrowserTools:
    """Tests for browser_tools module."""
    
    def test_browser_open_url_error_handling(self):
        """Test browser open URL error handling."""
        from tools_modules.browser_tools import browser_open_url
        
        with patch('tools_modules.browser_tools.httpx') as mock_httpx:
            mock_httpx.get.side_effect = Exception("Connection failed")
            
            result = browser_open_url("https://example.com")
            
            assert result['status'] == 'error'
    
    def test_browser_click_element_success(self):
        """Test clicking browser element."""
        from tools_modules.browser_tools import browser_click_element
        
        result = browser_click_element("button#submit", "tab1")
        
        assert result['status'] == 'success'
        assert 'tab_id' in result


class TestVisionTools:
    """Tests for vision_tools module."""
    
    def test_text_to_audio_file_structure(self):
        """Test text to audio file returns proper structure."""
        from tools_modules.vision_tools import text_to_audio_file
        
        result = text_to_audio_file("Hello world")
        
        assert isinstance(result, dict)
        assert 'status' in result
    
    def test_convert_media_format_error_handling(self):
        """Test media format conversion error handling."""
        from tools_modules.vision_tools import convert_media_format
        
        result = convert_media_format("/nonexistent/file.mp4", "mp3")
        
        assert result['status'] == 'error'


class TestSecurityTools:
    """Tests for security_tools module."""
    
    def test_audit_network_security_structure(self):
        """Test network audit returns proper structure."""
        from tools_modules.security_tools import audit_network_security
        
        result = audit_network_security("127.0.0.1")
        
        assert isinstance(result, dict)
        assert 'status' in result
    
    def test_audit_website_security_headers(self):
        """Test website security header checking."""
        from tools_modules.security_tools import audit_website_security
        
        with patch('tools_modules.security_tools.httpx') as mock_httpx:
            mock_response = MagicMock()
            mock_response.headers = {}
            mock_response.status_code = 200
            mock_httpx.get.return_value = mock_response
            
            result = audit_website_security("http://example.com")
            
            assert result['status'] == 'success'
            assert 'findings' in result


class TestSwarmTools:
    """Tests for swarm_tools module."""
    
    def test_spawn_background_subagent_structure(self):
        """Test spawning sub-agent returns proper structure."""
        from tools_modules.swarm_tools import spawn_background_subagent
        
        result = spawn_background_subagent("Test task", "Researcher")
        
        assert result['status'] == 'success'
        assert 'subagent_id' in result
    
    def test_check_subagent_status_structure(self):
        """Test checking sub-agent status."""
        from tools_modules.swarm_tools import check_subagent_status
        
        result = check_subagent_status("abc123")
        
        assert result['status'] == 'success'
        assert 'state' in result
    
    def test_conduct_ai_meeting_structure(self):
        """Test AI meeting returns proper structure."""
        from tools_modules.swarm_tools import conduct_ai_meeting
        
        result = conduct_ai_meeting("Test topic", "Alice, Bob", rounds=2)
        
        assert result['status'] == 'success'
        assert 'summary' in result


class TestDataTools:
    """Tests for data_tools module."""
    
    def test_analyze_dataset_error_handling(self):
        """Test dataset analysis error handling."""
        from tools_modules.data_tools import analyze_dataset_csv_json
        
        result = analyze_dataset_csv_json("/nonexistent/file.csv")
        
        assert result['status'] == 'error'
