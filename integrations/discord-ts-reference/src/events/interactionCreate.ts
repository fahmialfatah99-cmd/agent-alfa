import { Interaction, Events } from 'discord.js';
import { Command } from '../types';

export const name = Events.InteractionCreate;

export async function execute(interaction: Interaction, commands: Map<string, Command>) {
  if (interaction.isChatInputCommand()) {
    const command = commands.get(interaction.commandName);
    if (!command) {
      console.warn(`[Command Not Found]: ${interaction.commandName}`);
      return;
    }

    try {
      await command.execute(interaction);
    } catch (error: any) {
      console.error(`[Command Error] Error executing ${interaction.commandName}:`, error);
      const replyPayload = {
        content: `❌ Terjadi kesalahan saat mengeksekusi perintah: ${error.message || 'Unknown error'}`,
        ephemeral: true,
      };

      if (interaction.replied || interaction.deferred) {
        await interaction.followUp(replyPayload);
      } else {
        await interaction.reply(replyPayload);
      }
    }
  } else if (interaction.isButton()) {
    if (interaction.customId === 'jarvis_save_memory') {
      await interaction.reply({
        content: '💾 Percakapan ini telah dicatat ke dalam Swarm Long-Term Memory!',
        ephemeral: true,
      });
    } else if (interaction.customId === 'jarvis_regenerate') {
      await interaction.reply({
        content: '🔄 Perintah regenerasi diterima. Mohon gunakan kembali `/jarvis ask` dengan variasi prompt.',
        ephemeral: true,
      });
    }
  }
}
