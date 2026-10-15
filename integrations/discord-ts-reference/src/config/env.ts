import dotenv from 'dotenv';
import path from 'path';
import { BotConfig } from '../types';

dotenv.config();

export const config: BotConfig = {
  token: process.env.DISCORD_TOKEN || '',
  clientId: process.env.DISCORD_CLIENT_ID || '',
  guildId: process.env.DISCORD_GUILD_ID,
  llm: {
    provider: process.env.LLM_PROVIDER || 'openai_compatible',
    baseUrl: process.env.LLM_BASE_URL || 'http://localhost:11434/v1',
    apiKey: process.env.LLM_API_KEY || 'default_key',
    model: process.env.LLM_MODEL || 'llama3:latest',
    systemPrompt:
      process.env.LLM_SYSTEM_PROMPT ||
      'You are Jarvis ALFA, an advanced autonomous AI Swarm companion and Mission Control Orchestrator. Respond concisely and helpfully.',
  },
  swarmDataPath:
    process.env.SWARM_DATA_PATH ||
    path.resolve('/home/fahmial/Dokumen/ALFA_SWARM_OUTPUTS'),
};
