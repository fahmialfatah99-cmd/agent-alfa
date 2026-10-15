import { LLMMessage, LLMResponse } from '../types';
import { config } from '../config/env';

export class LLMClient {
  private baseUrl: string;
  private apiKey: string;
  private model: string;
  private defaultSystemPrompt: string;

  constructor() {
    this.baseUrl = config.llm.baseUrl.replace(/\/+$/, '');
    this.apiKey = config.llm.apiKey;
    this.model = config.llm.model;
    this.defaultSystemPrompt = config.llm.systemPrompt;
  }

  /**
   * Mengirim chat completions ke LLM endpoint (OpenAI / Ollama / Local LLM)
   */
  async chat(
    messages: LLMMessage[],
    options?: { temperature?: number; max_tokens?: number }
  ): Promise<LLMResponse> {
    const formattedMessages = [
      { role: 'system', content: this.defaultSystemPrompt },
      ...messages,
    ];

    const endpoint = `${this.baseUrl}/chat/completions`;

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.apiKey}`,
        },
        body: JSON.stringify({
          model: this.model,
          messages: formattedMessages,
          temperature: options?.temperature ?? 0.7,
          max_tokens: options?.max_tokens ?? 1024,
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `LLM API Error (${response.status} ${response.statusText}): ${errorText}`
        );
      }

      const data: any = await response.json();
      const choice = data.choices?.[0];
      const text = choice?.message?.content || 'Tidak ada balasan dari model LLM.';

      return {
        text,
        usage: data.usage
          ? {
              promptTokens: data.usage.prompt_tokens,
              completionTokens: data.usage.completion_tokens,
              totalTokens: data.usage.total_tokens,
            }
          : undefined,
        model: data.model || this.model,
        finishReason: choice?.finish_reason,
      };
    } catch (error: any) {
      // Fallback graceful degradation jika service offline atau network error
      console.error('[LLMClient Error]:', error.message || error);
      throw error;
    }
  }

  /**
   * Helper one-shot query
   */
  async ask(prompt: string, context?: string): Promise<string> {
    const messages: LLMMessage[] = [];
    if (context) {
      messages.push({
        role: 'user',
        content: `Konteks Tambahan:\n${context}\n\nPertanyaan:\n${prompt}`,
      });
    } else {
      messages.push({ role: 'user', content: prompt });
    }

    const res = await this.chat(messages);
    return res.text;
  }
}

export const llmClient = new LLMClient();
