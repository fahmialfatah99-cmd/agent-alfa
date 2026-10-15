import {
  ChatInputCommandInteraction,
  SlashCommandBuilder,
  EmbedBuilder,
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  ModalBuilder,
  TextInputBuilder,
  TextInputStyle,
} from 'discord.js';
import { Command } from '../types';
import { swarmService } from '../services/swarmService';

export const swarmCommand: Command = {
  data: new SlashCommandBuilder()
    .setName('swarm')
    .setDescription('Kendali dan orkestrasi swarm ALFA otonom')
    .addSubcommand((sub) =>
      sub
        .setName('status')
        .setDescription('Cek status live semua unit agen dan host server')
        .addBooleanOption((opt) =>
          opt
            .setName('verbose')
            .setDescription('Tampilkan detail metrik RAM, CPU, dan status sub-proses')
            .setRequired(false)
        )
    )
    .addSubcommand((sub) =>
      sub
        .setName('dispatch')
        .setDescription('Delegasikan tugas baru ke ALFA Swarm War Room')
        .addStringOption((opt) =>
          opt
            .setName('task')
            .setDescription('Judul tugas singkat (opsional jika ingin direct)')
            .setRequired(false)
        )
    ),

  async execute(interaction: ChatInputCommandInteraction) {
    const subcommand = interaction.options.getSubcommand();

    if (subcommand === 'status') {
      const verbose = interaction.options.getBoolean('verbose') || false;
      const statusData = swarmService.getSwarmStatus();
      const recentLogs = swarmService.getRecentLogs(3);

      const agentList = statusData.agents
        .map((a) => `• **${a.name}**: \`[${a.status}]\` — *${a.role}*`)
        .join('\n');

      const embed = new EmbedBuilder()
        .setTitle('🏛️ ALFA Swarm Mission Control Status')
        .setColor(0xfee75c)
        .setDescription('Status orkestrator dan agen otonom real-time:')
        .addFields(
          { name: '🤖 Active Swarm Units', value: agentList },
          {
            name: '🖥️ Host Health Metrics',
            value: `Uptime: ${statusData.systemMetrics.uptimeSec}s | Memory RSS: ${statusData.systemMetrics.memoryRssMb}MB | Node: ${statusData.systemMetrics.nodeVersion}`,
          },
          {
            name: '📜 Recent Live Logs',
            value: recentLogs.join('\n') || 'Tidak ada log aktif.',
          }
        )
        .setTimestamp();

      if (verbose) {
        embed.addFields({
          name: '⚙️ Verbose Runtime Internals',
          value: `Platform: ${statusData.systemMetrics.platform} | Heap: ${statusData.systemMetrics.memoryHeapMb}MB`,
        });
      }

      const row = new ActionRowBuilder<ButtonBuilder>().addComponents(
        new ButtonBuilder()
          .setCustomId('swarm_refresh')
          .setLabel('Refresh Status')
          .setStyle(ButtonStyle.Primary)
          .setEmoji('🔄'),
        new ButtonBuilder()
          .setCustomId('swarm_view_feed')
          .setLabel('Live Logs')
          .setStyle(ButtonStyle.Secondary)
          .setEmoji('📜'),
        new ButtonBuilder()
          .setLabel('Open Web Dashboard')
          .setStyle(ButtonStyle.Link)
          .setURL('http://localhost:3000/dashboard')
          .setEmoji('🌐')
      );

      await interaction.reply({ embeds: [embed], components: [row] });
    } else if (subcommand === 'dispatch') {
      const directTask = interaction.options.getString('task');

      if (directTask) {
        const mission = swarmService.dispatchMission(directTask, 'Dispatched directly via slash command');
        const embed = new EmbedBuilder()
          .setTitle('🚀 Mission Dispatched to Swarm')
          .setColor(0x57f287)
          .setDescription(`Tugas berhasil didelegasikan ke swarm engine.`)
          .addFields(
            { name: 'Mission ID', value: `\`${mission.id}\``, inline: true },
            { name: 'Assigned Unit', value: mission.assignedAgent, inline: true },
            { name: 'Status', value: `\`${mission.status}\``, inline: true },
            { name: 'Instruction', value: mission.title }
          )
          .setTimestamp();

        await interaction.reply({ embeds: [embed] });
      } else {
        // Tampilkan Modal dialog untuk input terperinci
        const modal = new ModalBuilder()
          .setCustomId('modal_swarm_dispatch')
          .setTitle('🚀 Dispatch New Mission to Swarm');

        const titleInput = new TextInputBuilder()
          .setCustomId('mission_title')
          .setLabel('Judul Misi')
          .setStyle(TextInputStyle.Short)
          .setPlaceholder('Contoh: Riset tren framework AI 2026')
          .setRequired(true)
          .setMinLength(5)
          .setMaxLength(100);

        const descInput = new TextInputBuilder()
          .setCustomId('mission_desc')
          .setLabel('Spesifikasi & Objektif Misi')
          .setStyle(TextInputStyle.Paragraph)
          .setPlaceholder('Jelaskan requirement, output yang diharapkan, dan constraint...')
          .setRequired(true)
          .setMinLength(10)
          .setMaxLength(2000);

        const firstActionRow = new ActionRowBuilder<TextInputBuilder>().addComponents(titleInput);
        const secondActionRow = new ActionRowBuilder<TextInputBuilder>().addComponents(descInput);

        modal.addComponents(firstActionRow, secondActionRow);
        await interaction.showModal(modal);
      }
    }
  },
};
