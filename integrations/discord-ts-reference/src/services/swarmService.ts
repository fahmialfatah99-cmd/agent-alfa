import fs from 'fs';
import path from 'path';
import { config } from '../config/env';

export interface SwarmMission {
  id: string;
  title: string;
  description: string;
  status: 'QUEUED' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';
  assignedAgent: string;
  createdAt: string;
}

export class SwarmService {
  private dataDir: string;
  private feedFile: string;

  constructor() {
    this.dataDir = config.swarmDataPath;
    this.feedFile = path.join(this.dataDir, 'live_meeting_feed.jsonl');
  }

  /**
   * Mengambil status ringkasan agen swarm & server host
   */
  getSwarmStatus() {
    const memory = process.memoryUsage();
    return {
      agents: [
        { name: 'Alpha Lead', status: 'ONLINE', role: 'Mission Orchestrator' },
        { name: 'Researcher Prime', status: 'ONLINE', role: 'Data Mining & Intelligence' },
        { name: 'Strategic Planner', status: 'ONLINE', role: 'Architecture & UX' },
        { name: 'Code Crafter', status: 'ACTIVE', role: 'TypeScript & Systems Engineer' },
        { name: 'System Auditor', status: 'ONLINE', role: 'Security & Integrity' },
      ],
      systemMetrics: {
        uptimeSec: Math.floor(process.uptime()),
        memoryRssMb: Math.round(memory.rss / 1024 / 1024),
        memoryHeapMb: Math.round(memory.heapUsed / 1024 / 1024),
        nodeVersion: process.version,
        platform: process.platform,
      },
    };
  }

  /**
   * Membaca log terkini dari live meeting feed
   */
  getRecentLogs(limit: number = 5): string[] {
    try {
      if (!fs.existsSync(this.feedFile)) {
        return ['[INFO] Feed file live_meeting_feed.jsonl belum ditemukan.'];
      }
      const raw = fs.readFileSync(this.feedFile, 'utf-8');
      const lines = raw.trim().split('\n').filter(Boolean);
      const tail = lines.slice(-limit);
      return tail.map((line) => {
        try {
          const parsed = JSON.parse(line);
          const time = parsed.timestamp ? `[${parsed.timestamp.split('T')[1]?.substring(0, 8)}] ` : '';
          const sender = parsed.sender || 'Agent';
          const text = parsed.text || parsed.message || JSON.stringify(parsed);
          return `${time}**${sender}**: ${text.substring(0, 120)}`;
        } catch {
          return line.substring(0, 120);
        }
      });
    } catch (err: any) {
      return [`[ERROR] Gagal membaca logs: ${err.message}`];
    }
  }

  /**
   * Membuat dan mencatat misi baru ke dalam daftar misi swarm
   */
  dispatchMission(title: string, description: string, agent: string = 'Code Crafter'): SwarmMission {
    const missionId = `MISSION-${Date.now().toString(36).toUpperCase()}`;
    const mission: SwarmMission = {
      id: missionId,
      title,
      description,
      status: 'QUEUED',
      assignedAgent: agent,
      createdAt: new Date().toISOString(),
    };

    const missionLogPath = path.join(this.dataDir, 'dispatched_missions.json');
    let missions: SwarmMission[] = [];
    if (fs.existsSync(missionLogPath)) {
      try {
        missions = JSON.parse(fs.readFileSync(missionLogPath, 'utf-8'));
      } catch {
        missions = [];
      }
    }
    missions.push(mission);
    fs.writeFileSync(missionLogPath, JSON.stringify(missions, null, 2), 'utf-8');

    return mission;
  }
}

export const swarmService = new SwarmService();
