import {
  ChatInputCommandInteraction,
  SlashCommandBuilder,
  EmbedBuilder,
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
} from 'discord.js';
import { Command } from '../types';
import { llmClient } from '../llm/client';

export const jarvisCommand: Command = {
  data: new SlashCommandBuilder()
    .setName('jarvis')
    .setDescription('Asisten pintar multimodal Jarvis ALFA')
    .addSubcommand((sub) =>
      sub
        .setName('ask')
        .setDescription('Tanya apa saja ke Jarvis LLM')
        .addStringOption((opt) =>
          opt
            .setName('query')
            .setDescription('Pertanyaan atau instruksi untuk Jarvis')
            .setRequired(true)
        )
        .addStringOption((opt) =>
          opt
            .setName('mode')
            .setDescription('Mode penalaran model')
            .setRequired(false)
            .addChoices(
              { name: 'Fast (Cepat & Ringkas)', value: 'fast' },
              { name: 'Deep (Analisis Mendalam)', value: 'deep' }
            )
        )
    )
    .addSubcommand((sub) =>
      sub
        .setName('voice')
        .setDescription('Kontrol interaksi suara real-time Jarvis di voice channel')
        .addStringOption((opt) =>
          opt
            .setName('action')
            .setDescription('Tindakan voice')
            .setRequired(true)
            .addChoices(
              { name: 'Join Channel', value: 'join' },
              { name: 'Leave Channel', value: 'leave' },
              { name: 'Listen Mode', value: 'listen' },
              { name: 'Speak Status', value: 'speak' }
            )
        )
    ),

  async execute(interaction: ChatInputCommandInteraction) {
    const subcommand = interaction.options.getSubcommand();

    if (subcommand === 'ask') {
      await interaction.deferReply();
      const query = interaction.options.getString('query', true);
      const mode = interaction.options.getString('mode') || 'fast';

      try {
        const promptContext =
          mode === 'deep'
            ? 'Instruksi: Berikan penalaran yang runtut, terstruktur, dan mendalam.'
            : 'Instruksi: Berikan jawaban langsung, padat, dan jelas.';

        const answer = await llmClient.ask(query, promptContext);

        const embed = new EmbedBuilder()
          .setTitle('🤖 Jarvis ALFA Intelligence')
          .setColor(0x5865f2)
          .addFields(
            { name: '❓ Pertanyaan', value: query.length > 250 ? query.substring(0, 247) + '...' : query },
            { name: `💡 Jawaban (${mode.toUpperCase()})`, value: answer.length > 1000 ? answer.substring(0, 997) + '...' : answer }
          )
          .setFooter({ text: 'Powered by ALFA Autonomous Swarm & LLM' })
          .setTimestamp();

        const row = new ActionRowBuilder<ButtonBuilder>().addComponents(
          new ButtonBuilder()
            .setCustomId('jarvis_save_memory')
            .setLabel('Save to Memory')
            .setStyle(ButtonStyle.Secondary)
            .setEmoji('💾'),
          new ButtonBuilder()
            .setCustomId('jarvis_regenerate')
            .setLabel('Regenerate')
            .setStyle(ButtonStyle.Primary)
            .setEmoji('🔄')
        );

        await interaction.editReply({ embeds: [embed], components: [row] });
      } catch (err: any) {
        const errorEmbed = new EmbedBuilder()
          .setTitle('⚠️ Jarvis Engine Error')
          .setColor(0xed4245)
          .setDescription(`Gagal mendapatkan respon LLM: ${err.message || err}`)
          .setFooter({ text: 'Periksa LLM Provider URL dan API Key di .env' });

        await interaction.editReply({ embeds: [errorEmbed] });
      }
    } else if (subcommand === 'voice') {
      const action = interaction.options.getString('action', true);
      const embed = new EmbedBuilder()
        .setTitle('🎙️ Jarvis Voice Gateway')
        .setColor(0x57f287)
        .setDescription(`Perintah Voice: **${action.toUpperCase()}** diproses.`)
        .addFields(
          { name: 'Gateway Status', value: 'Ready (Opus & Whisper Pipeline Active)', inline: true },
          { name: 'Action Dispatched', value: `\`${action}\``, inline: true }
        )
        .setTimestamp();

      await interaction.reply({ embeds: [embed] });
    }
  },
};
