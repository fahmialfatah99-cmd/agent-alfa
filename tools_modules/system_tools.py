"""
System Monitoring & Information Tools Module
Provides system stats, process monitoring, and system information.
"""

import datetime
import os
import platform
import socket
import subprocess
from typing import Any, Dict, List, Optional, TypedDict

import psutil


# =============================================================================
# TYPE DEFINITIONS
# =============================================================================

class SystemStats(TypedDict):
    """Type definition for system statistics."""
    cpu_percent: float
    cpu_freq_mhz: float
    cpu_cores_logical: int
    cpu_cores_physical: int
    ram_total_mb: float
    ram_used_mb: float
    ram_free_mb: float
    ram_percent: float
    disk_total_gb: float
    disk_used_gb: float
    disk_free_gb: float
    disk_percent: float
    boot_time: str
    uptime_seconds: int
    uptime_human: str
    hostname: str
    platform_system: str
    platform_release: str
    platform_version: str
    platform_machine: str
    processor: str
    python_version: str
    working_directory: str
    username: str
    processes: List[Dict[str, Any]]


def get_system_stats() -> Dict[str, Any]:
    """
    Get comprehensive system statistics including CPU, RAM, disk, and process information.
    
    Returns:
        Dict containing system statistics with keys:
        - cpu_percent: CPU usage percentage
        - cpu_freq_mhz: CPU frequency in MHz
        - cpu_cores_logical: Number of logical CPU cores
        - cpu_cores_physical: Number of physical CPU cores
        - ram_total_mb: Total RAM in MB
        - ram_used_mb: Used RAM in MB
        - ram_free_mb: Free RAM in MB
        - ram_percent: RAM usage percentage
        - disk_total_gb: Total disk space in GB
        - disk_used_gb: Used disk space in GB
        - disk_free_gb: Free disk space in GB
        - disk_percent: Disk usage percentage
        - boot_time: System boot time as ISO format string
        - uptime_seconds: System uptime in seconds
        - uptime_human: Human-readable uptime string
        - hostname: System hostname
        - platform_system: Operating system name
        - platform_release: OS release version
        - platform_version: OS version
        - platform_machine: Machine architecture
        - processor: Processor information
        - python_version: Python version string
        - working_directory: Current working directory
        - username: Current username
        - processes: List of top 10 processes by CPU usage
    """
    try:
        # CPU Information
        cpu_percent = psutil.cpu_percent(interval=0.5)
        cpu_freq = psutil.cpu_freq()
        cpu_freq_mhz = cpu_freq.current if cpu_freq else 0.0
        cpu_cores_logical = psutil.cpu_count(logical=True) or 0
        cpu_cores_physical = psutil.cpu_count(logical=False) or 0
        
        # RAM/Memory Information
        ram = psutil.virtual_memory()
        ram_total_mb = round(ram.total / (1024 * 1024), 2)
        ram_used_mb = round(ram.used / (1024 * 1024), 2)
        ram_free_mb = round(ram.available / (1024 * 1024), 2)
        ram_percent = ram.percent
        
        # Disk Information
        disk = psutil.disk_usage('/')
        disk_total_gb = round(disk.total / (1024 * 1024 * 1024), 2)
        disk_used_gb = round(disk.used / (1024 * 1024 * 1024), 2)
        disk_free_gb = round(disk.free / (1024 * 1024 * 1024), 2)
        disk_percent = disk.percent
        
        # Boot time and uptime
        boot_time_obj = datetime.datetime.fromtimestamp(psutil.boot_time())
        boot_time_str = boot_time_obj.isoformat()
        uptime_seconds = int((datetime.datetime.now() - boot_time_obj).total_seconds())
        
        # Format uptime in human-readable form
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        uptime_human = f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m"
        
        # System information
        hostname = socket.gethostname()
        platform_system = platform.system()
        platform_release = platform.release()
        platform_version = platform.version()
        platform_machine = platform.machine()
        processor = platform.processor() or "Unknown"
        python_version = platform.python_version()
        working_directory = os.getcwd()
        username = os.getenv('USERNAME') if platform.system() == 'Windows' else os.getenv('USER') or 'Unknown'
        
        # Top processes by CPU usage
        processes = []
        try:
            for proc in sorted(psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']), 
                             key=lambda p: p.info['cpu_percent'] or 0, 
                             reverse=True)[:10]:
                try:
                    processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'] or 'Unknown',
                        'cpu_percent': round(proc.info['cpu_percent'] or 0, 2),
                        'memory_percent': round(proc.info['memory_percent'] or 0, 2)
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        
        return {
            'status': 'success',
            'data': {
                'cpu_percent': cpu_percent,
                'cpu_freq_mhz': round(cpu_freq_mhz, 2),
                'cpu_cores_logical': cpu_cores_logical,
                'cpu_cores_physical': cpu_cores_physical,
                'ram_total_mb': ram_total_mb,
                'ram_used_mb': ram_used_mb,
                'ram_free_mb': ram_free_mb,
                'ram_percent': ram_percent,
                'disk_total_gb': disk_total_gb,
                'disk_used_gb': disk_used_gb,
                'disk_free_gb': disk_free_gb,
                'disk_percent': disk_percent,
                'boot_time': boot_time_str,
                'uptime_seconds': uptime_seconds,
                'uptime_human': uptime_human,
                'hostname': hostname,
                'platform_system': platform_system,
                'platform_release': platform_release,
                'platform_version': platform_version,
                'platform_machine': platform_machine,
                'processor': processor,
                'python_version': python_version,
                'working_directory': working_directory,
                'username': username,
                'processes': processes
            }
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Failed to get system stats: {str(e)}'
        }
