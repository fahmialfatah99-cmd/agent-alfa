import {
  Client,
  GatewayIntentBits,
  Partials,
  REST,
  Routes,
} from 'discord.js';
import { config } from './config/env';
import { Command } from './types';
import { jarvisCommand } from './commands/jarvis';
import { swarmCommand } from './commands/swarm';
import * as readyEvent from './events/ready';
import * as interactionCreateEvent from './events/interactionCreate';

export class AlfaDiscordBot {
  public client: Client;
  public commands: Map<string, Command>;

  constructor() {
    this.client = new Client({
      intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.GuildVoiceStates,
      ],
      partials: [Partials.Channel, Partials.Message],
    });

    this.commands = new Map<string, Command>();
    this.registerCommands();
    this.registerEvents();
  }

  private registerCommands(): void {
    const commandList: Command[] = [jarvisCommand, swarmCommand];
    for (const cmd of commandList) {
      this.commands.set(cmd.data.name, cmd);
    }
    console.log(`[AlfaDiscordBot] ${this.commands.size} perintah berhasil didaftarkan ke memori.`);
  }

  private registerEvents(): void {
    this.client.once(readyEvent.name, () => readyEvent.execute(this.client));
    this.client.on(interactionCreateEvent.name, (interaction) =>
      interactionCreateEvent.execute(interaction, this.commands)
    );
  }

  /**
   * Mendaftarkan Slash Commands ke Discord API REST
   */
  public async deploySlashCommands(): Promise<void> {
    if (!config.token || !config.clientId) {
      console.warn('[Deploy Warning] DISCORD_TOKEN atau DISCORD_CLIENT_ID belum diatur di env. Lewati sinkronisasi REST.');
      return;
    }

    const rest = new REST({ version: '10' }).setToken(config.token);
    const body = Array.from(this.commands.values()).map((c) => c.data.toJSON());

    try {
      console.log(`[Deploy] Memulai sinkronisasi ${body.length} application (/) commands...`);
      if (config.guildId) {
        await rest.put(
          Routes.applicationGuildCommands(config.clientId, config.guildId),
          { body }
        );
        console.log(`[Deploy] Berhasil mendaftarkan commands ke Guild: ${config.guildId}`);
      } else {
        await rest.put(Routes.applicationCommands(config.clientId), { body });
        console.log('[Deploy] Berhasil mendaftarkan global slash commands.');
      }
    } catch (error: any) {
      console.error('[Deploy Error] Gagal deploy slash commands:', error.message || error);
    }
  }

  /**
   * Menjalankan bot Discord
   */
  public async start(): Promise<void> {
    if (!config.token) {
      console.warn('[AlfaDiscordBot] DISCORD_TOKEN kosong. Bot tidak dapat terkoneksi ke Gateway Discord langsung tanpa token.');
      return;
    }

    try {
      await this.deploySlashCommands();
      await this.client.login(config.token);
    } catch (error: any) {
      console.error('[AlfaDiscordBot Error] Gagal login ke Discord:', error.message || error);
    }
  }
}
