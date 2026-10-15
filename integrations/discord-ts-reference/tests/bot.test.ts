import { AlfaDiscordBot } from '../src/bot';
import { llmClient } from '../src/llm/client';
import { SwarmService } from '../src/services/swarmService';

async function runTestSuite() {
  console.log('🧪 [TEST SUITE] Memulai pengujian unit & integrasi ALFA Discord Bot TS...\n');

  let passed = 0;
  let total = 0;

  function assert(condition: boolean, desc: string) {
    total++;
    if (condition) {
      console.log(`  ✅ PASS: ${desc}`);
      passed++;
    } else {
      console.error(`  ❌ FAIL: ${desc}`);
    }
  }

  // 1. Inisialisasi Bot Core & Commands
  console.log('1. Pengujian Bot Core Initialization:');
  const bot = new AlfaDiscordBot();
  assert(bot.client !== null && bot.client !== undefined, 'Discord Client instance berhasil terinisialisasi');
  assert(bot.commands.has('jarvis'), 'Perintah /jarvis terdaftar');
  assert(bot.commands.has('swarm'), 'Perintah /swarm terdaftar');
  assert(bot.commands.size === 2, `Jumlah perintah terdaftar sesuai (expected: 2, actual: ${bot.commands.size})`);

  // 2. Swarm Service
  console.log('\n2. Pengujian SwarmService:');
  const swarmService = new SwarmService();
  const status = swarmService.getSwarmStatus();
  assert(Array.isArray(status.agents) && status.agents.length >= 5, 'Swarm agents list valid dan memiliki minimal 5 agent');
  assert(typeof status.systemMetrics.uptimeSec === 'number', 'Metrics uptime berupa number');
  assert(typeof status.systemMetrics.memoryRssMb === 'number', 'Metrics memory RSS terdeteksi');

  const mission = swarmService.dispatchMission('Unit Test Mission', 'Automated verification test', 'Code Crafter');
  assert(mission.title === 'Unit Test Mission', 'Dispatch mission menghasilkan judul yang cocok');
  assert(mission.status === 'QUEUED', 'Status mission awal adalah QUEUED');
  assert(mission.id.startsWith('MISSION-'), 'Format Mission ID valid');

  const recentLogs = swarmService.getRecentLogs(3);
  assert(Array.isArray(recentLogs), 'getRecentLogs menghasilkan array');

  // 3. LLM Client Fallback & Contract Verification
  console.log('\n3. Pengujian LLM Client:');
  assert(typeof llmClient.chat === 'function', 'LLMClient memiliki method chat()');
  assert(typeof llmClient.ask === 'function', 'LLMClient memiliki method ask()');

  console.log(`\n========================================`);
  console.log(`Hasil Pengujian: ${passed}/${total} lolos.`);
  if (passed === total) {
    console.log(`🏆 SEMUA PENGUJIAN BOT TS DINILAI SUKSES.`);
  } else {
    console.error(`⚠️ Beberapa pengujian gagal.`);
    process.exit(1);
  }
}

runTestSuite().catch((e) => {
  console.error('Fatal Test Runner Error:', e);
  process.exit(1);
});
