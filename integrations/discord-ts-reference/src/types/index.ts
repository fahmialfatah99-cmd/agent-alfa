import { ChatInputCommandInteraction, SlashCommandBuilder, SlashCommandSubcommandsOnlyBuilder } from 'discord.js';

export interface Command {
  data: SlashCommandBuilder | SlashCommandSubcommandsOnlyBuilder | any;
  execute: (interaction: ChatInputCommandInteraction) => Promise<void>;
}

export interface LLMMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface LLMResponse {
  text: string;
  usage?: {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
  };
  model: string;
  finishReason?: string;
}

export interface BotConfig {
  token: string;
  clientId: string;
  guildId?: string;
  llm: {
    provider: string;
    baseUrl: string;
    apiKey: string;
    model: string;
    systemPrompt: string;
  };
  swarmDataPath: string;
}
