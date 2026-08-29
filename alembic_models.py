"""SQLAlchemy Models for ALFA Database - Used by Alembic for migrations."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey, Index
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class ChatHistory(Base):
    """Chat history table."""
    __tablename__ = 'chat_history'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    chat_id = Column(String(255), nullable=False, index=True)
    message_id = Column(Integer)
    role = Column(String(50))  # user, assistant, system, tool
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    model_used = Column(String(100))
    tokens_used = Column(Integer)
    
    __table_args__ = (
        Index('idx_user_chat', 'user_id', 'chat_id'),
    )


class KnowledgeMemory(Base):
    """Long-term knowledge memory table."""
    __tablename__ = 'knowledge_memory'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    key_topic = Column(String(500), nullable=False)
    content = Column(Text)
    category = Column(String(100), default='general')
    tags = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_user_topic', 'user_id', 'key_topic'),
    )


class Reminder(Base):
    """Reminders table."""
    __tablename__ = 'reminders'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    reminder_time = Column(DateTime, nullable=False)
    message = Column(Text)
    is_recurring = Column(Boolean, default=False)
    interval_minutes = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent = Column(Boolean, default=False)


class UserSetting(Base):
    """User settings table."""
    __tablename__ = 'user_settings'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, unique=True, index=True)
    settings_json = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApiKey(Base):
    """API keys table (encrypted)."""
    __tablename__ = 'api_keys'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    provider = Column(String(100), default='gemini')
    api_key = Column(Text, nullable=False)  # Encrypted
    base_url = Column(String(500))
    default_model = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CustomAgent(Base):
    """Custom agents table."""
    __tablename__ = 'custom_agents'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    role = Column(String(255))
    persona = Column(Text)
    system_instruction = Column(Text)
    provider = Column(String(100), default='gemini')
    model = Column(String(255))
    avatar_emoji = Column(String(10))
    color_theme = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TokenUsage(Base):
    """Token usage tracking table."""
    __tablename__ = 'token_usage'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    provider = Column(String(100))
    model = Column(String(255))
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class VectorDocument(Base):
    """Vector brain documents table."""
    __tablename__ = 'vector_documents'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    content = Column(Text)
    file_path = Column(String(1000))
    category = Column(String(100), default='general')
    embedding_model = Column(String(255))
    vector_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class VaultSecret(Base):
    """Vault secrets table (encrypted)."""
    __tablename__ = 'vault_secrets'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    value = Column(Text, nullable=False)  # Encrypted
    category = Column(String(100), default='api_key')
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class RecurringTask(Base):
    """Recurring tasks table."""
    __tablename__ = 'recurring_tasks'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    prompt_instruction = Column(Text)
    interval_minutes = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    last_run = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class SubAgent(Base):
    """Background sub-agents table."""
    __tablename__ = 'sub_agents'
    
    id = Column(Integer, primary_key=True)
    subagent_id = Column(String(50), unique=True, nullable=False, index=True)
    task_description = Column(Text)
    agent_role = Column(String(255))
    status = Column(String(50), default='running')  # running, completed, failed
    progress = Column(Integer, default=0)
    result = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)


class FocusSession(Base):
    """Focus sessions table."""
    __tablename__ = 'focus_sessions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    title = Column(String(500))
    duration_minutes = Column(Integer, default=25)
    notes = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    status = Column(String(50), default='active')  # active, completed, cancelled
