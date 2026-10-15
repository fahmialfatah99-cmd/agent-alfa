import { AlfaDiscordBot } from './bot';

async function main() {
  console.log('🚀 Memulai ALFA Swarm Discord Bot Core (TypeScript)...');
  const bot = new AlfaDiscordBot();
  await bot.start();
}

if (require.main === module) {
  main().catch((err) => {
    console.error('Fatal bot runtime error:', err);
    process.exit(1);
  });
}

export { AlfaDiscordBot };
