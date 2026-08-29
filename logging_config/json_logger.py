"""Structured JSON Logging Configuration for ALFA Agent."""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from pythonjsonlogger import jsonlogger


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with additional fields."""
    
    def add_fields(
        self, 
        log_record: Dict[str, Any], 
        record: logging.LogRecord, 
        message: str
    ) -> None:
        """Add custom fields to log records."""
        super().add_fields(log_record, record, message)
        
        # Add timestamp in ISO format
        log_record['timestamp'] = datetime.utcnow().isoformat() + 'Z'
        
        # Add level as severity
        log_record['severity'] = record.levelname
        
        # Add location info
        log_record['location'] = {
            'file': record.pathname,
            'line': record.lineno,
            'function': record.funcName
        }
        
        # Add thread and process info
        log_record['thread'] = {
            'id': record.thread,
            'name': record.threadName
        }
        log_record['process'] = {
            'id': record.process,
            'name': record.processName
        }
        
        # Add extra fields if present
        if hasattr(record, 'user_id'):
            log_record['user_id'] = record.user_id
        if hasattr(record, 'chat_id'):
            log_record['chat_id'] = record.chat_id
        if hasattr(record, 'request_id'):
            log_record['request_id'] = record.request_id


def setup_json_logging(
    log_level: int = logging.INFO,
    log_file: Optional[str] = None,
    console_output: bool = True
) -> logging.Logger:
    """
    Setup structured JSON logging for the application.
    
    Args:
        log_level: Minimum log level (default: INFO)
        log_file: Path to log file (optional)
        console_output: Whether to output to console (default: True)
    
    Returns:
        Root logger configured with JSON formatting
    """
    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Create JSON formatter
    json_formatter = CustomJsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s',
        rename_fields={
            'asctime': 'timestamp',
            'name': 'logger',
            'levelname': 'level'
        }
    )
    
    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(json_formatter)
        logger.addHandler(console_handler)
    
    # File handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(json_formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name.
    
    Args:
        name: Logger name (usually __name__)
    
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


# Example usage and context managers
class LogContext:
    """Context manager for adding contextual information to logs."""
    
    def __init__(self, **kwargs):
        self.context = kwargs
        self.old_factory = None
    
    def __enter__(self):
        self.old_factory = logging.getLogRecordFactory()
        
        def factory(*args, **kwargs):
            record = self.old_factory(*args, **kwargs)
            for key, value in self.context.items():
                setattr(record, key, value)
            return record
        
        logging.setLogRecordFactory(factory)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.old_factory:
            logging.setLogRecordFactory(self.old_factory)


# Convenience functions for common logging patterns
def log_user_action(logger: logging.Logger, user_id: str, action: str, details: Optional[Dict] = None):
    """Log a user action with context."""
    extra = {'user_id': user_id, 'action': action}
    if details:
        extra['details'] = details
    
    log_record = logging.LogRecord(
        name=logger.name,
        level=logging.INFO,
        pathname='',
        lineno=0,
        msg=f"User action: {action}",
        args=(),
        exc_info=None,
        func=''
    )
    for k, v in extra.items():
        setattr(log_record, k, v)
    
    logger.handle(log_record)


def log_tool_execution(logger: logging.Logger, tool_name: str, status: str, duration_ms: float, result_size: int = 0):
    """Log tool execution metrics."""
    logger.info(
        f"Tool executed: {tool_name}",
        extra={
            'tool_name': tool_name,
            'status': status,
            'duration_ms': duration_ms,
            'result_size': result_size
        }
    )


def log_error_with_context(logger: logging.Logger, error: Exception, context: Optional[Dict] = None):
    """Log an error with additional context."""
    extra = {
        'error_type': type(error).__name__,
        'error_message': str(error)
    }
    if context:
        extra.update(context)
    
    logger.error(
        f"Error: {type(error).__name__}",
        exc_info=True,
        extra=extra
    )
