import { Client, Events } from 'discord.js';

export const name = Events.ClientReady;
export const once = true;

export function execute(client: Client) {
  console.log(`[ALFA Swarm Bot Ready] Masuk sebagai ${client.user?.tag} (ID: ${client.user?.id})`);
  client.user?.setPresence({
    activities: [{ name: 'ALFA War Room & LLM Hub' }],
    status: 'online',
  });
}
