#!/usr/bin/env node

const { Command } = require('commander');
const inquirer = require('@inquirer/prompts');
const chalk = require('chalk');
const fs = require('fs').promises;
const path = require('path');
const { exec } = require('child_process');
const util = require('util');
require('dotenv').config();

const execPromise = util.promisify(exec);
const program = new Command();

// Konfigurasi AI - Support multiple providers
const API_PROVIDER = process.env.AI_PROVIDER || 'openai'; // openai, anthropic, ollama
const API_KEY = process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY || '';
const API_BASE_URL = process.env.API_BASE_URL || 'https://api.openai.com/v1';

// Simple HTTP client untuk call API tanpa dependency tambahan
async function callAPI(messages, model) {
  const isOllama = API_PROVIDER === 'ollama';
  const url = isOllama 
    ? 'http://localhost:11434/api/chat' 
    : `${API_BASE_URL}/chat/completions`;

  let body;
  if (isOllama) {
    body = {
      model: model || 'llama3.1',
      messages: messages,
      stream: false
    };
  } else {
    body = {
      model: model || 'gpt-4o-mini',
      messages: messages,
      temperature: 0.7
    };
  }

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(isOllama ? {} : { 'Authorization': `Bearer ${API_KEY}` })
      },
      body: JSON.stringify(body)
    });

    if (!response.ok) {
      const errorData = await response.text();
      throw new Error(`HTTP ${response.status}: ${errorData}`);
    }

    const data = await response.json();
    
    if (isOllama) {
      return data.message.content;
    } else {
      return data.choices[0].message.content;
    }
  } catch (error) {
    throw error;
  }
}

const SYSTEM_PROMPT = `Anda adalah asisten coding ahli di CLI seperti Cursor/OpenCode. 
Tugas Anda:
1. Membantu user menulis, memperbaiki, dan menjelaskan kode.
2. Jika user meminta membuat file, berikan blok kode lengkap dengan nama file.
3. Jika user meminta menjalankan perintah, berikan perintah shell yang aman.
4. Jawab dengan ringkas, teknis, dan langsung pada inti masalah.
5. Gunakan format Markdown untuk kode.`;

let conversationHistory = [
  { role: "system", content: SYSTEM_PROMPT }
];

// Helper: Baca file konteks
async function readContext(filePath) {
  try {
    const content = await fs.readFile(filePath, 'utf-8');
    return `--- Isi file ${filePath} ---\n${content}`;
  } catch (err) {
    return `File ${filePath} tidak ditemukan atau tidak bisa dibaca.`;
  }
}

// Helper: Kirim ke LLM
async function askAI(prompt, contextFiles = []) {
  let messages = [...conversationHistory];
  
  if (contextFiles.length > 0) {
    const contextPromises = contextFiles.map(f => readContext(f));
    const contexts = await Promise.all(contextPromises);
    messages.push({ 
      role: "user", 
      content: `Konteks File:\n${contexts.join('\n\n')}\n\nPertanyaan: ${prompt}` 
    });
  } else {
    messages.push({ role: "user", content: prompt });
  }

  try {
    const model = API_PROVIDER === 'ollama' ? 'llama3.1' : 'gpt-4o-mini';
    const response = await callAPI(messages, model);
    
    // Update history (batasi agar tidak terlalu panjang)
    conversationHistory.push({ role: "user", content: prompt });
    conversationHistory.push({ role: "assistant", content: response });
    if (conversationHistory.length > 10) conversationHistory.shift();

    return response;
  } catch (error) {
    let errorMsg = chalk.red(`Error AI: ${error.message}`);
    
    if (!API_KEY && API_PROVIDER !== 'ollama') {
      errorMsg += '\n\n' + chalk.yellow('💡 Tips: Set OPENAI_API_KEY environment variable atau gunakan Ollama untuk offline mode.');
      errorMsg += '\n   Export: export OPENAI_API_KEY=sk-your-key-here';
      errorMsg += '\n   Atau install Ollama: curl -fsSL https://ollama.com/install.sh | sh';
    }
    
    return errorMsg;
  }
}

// Mode Interaktif (REPL)
async function startInteractiveMode() {
  console.log(chalk.blue.bold("\n🚀 DevCLI Mode Interaktif Aktif"));
  console.log(chalk.gray(`Provider: ${API_PROVIDER.toUpperCase()} | Model: ${API_PROVIDER === 'ollama' ? 'llama3.1' : 'gpt-4o-mini'}`));
  console.log(chalk.gray("Ketik 'exit' untuk keluar, 'clear' untuk reset chat.\n"));

  while (true) {
    const input = await inquirer.input({
      message: chalk.green('You: '),
    });

    if (input.toLowerCase() === 'exit') break;
    if (input.toLowerCase() === 'clear') {
      conversationHistory = [{ role: "system", content: SYSTEM_PROMPT }];
      console.log(chalk.yellow("Chat history dibersihkan."));
      continue;
    }
    if (!input.trim()) continue;

    const response = await askAI(input);
    console.log(chalk.cyan.bold("\nDevCLI:"));
    console.log(response);
    console.log("\n");
  }
}

// Setup CLI Commands
program
  .name('devcli')
  .description('AI Coding Assistant CLI seperti Cursor/OpenCode')
  .version('1.0.0');

program
  .command('chat')
  .description('Mulai sesi chat interaktif')
  .option('-f, --file <path>', 'Sertakan file sebagai konteks', (val, prev) => (prev ? [...prev, val] : [val]), [])
  .action(async (options) => {
    if (options.file && options.file.length > 0) {
      const initialPrompt = `Saya ingin mendiskusikan file-file ini: ${options.file.join(', ')}. Mohon analisis singkat.`;
      const response = await askAI(initialPrompt, options.file);
      console.log(chalk.cyan.bold("DevCLI:"));
      console.log(response);
      console.log("\n");
    }
    await startInteractiveMode();
  });

program
  .command('ask <question>')
  .description('Tanya pertanyaan cepat tanpa mode interaktif')
  .option('-f, --file <path>', 'Sertakan file sebagai konteks')
  .action(async (question, options) => {
    const contextFiles = options.file ? [options.file] : [];
    const response = await askAI(question, contextFiles);
    console.log(chalk.cyan.bold("DevCLI:"));
    console.log(response);
  });

program
  .command('run <command>')
  .description('Jalankan perintah shell')
  .action(async (cmd) => {
    console.log(chalk.yellow(`Menjalankan: ${cmd}...`));
    try {
      const { stdout, stderr } = await execPromise(cmd);
      if (stdout) console.log(stdout);
      if (stderr) console.error(chalk.red(stderr));
    } catch (error) {
      console.error(chalk.red(`Error: ${error.message}`));
    }
  });

program
  .command('config')
  .description('Tampilkan konfigurasi AI saat ini')
  .action(() => {
    console.log(chalk.blue.bold("\n📋 DevCLI Configuration:"));
    console.log(`  Provider: ${chalk.green(API_PROVIDER)}`);
    console.log(`  API Base URL: ${chalk.green(API_BASE_URL)}`);
    console.log(`  API Key Set: ${chalk.green(API_KEY ? 'Yes (****)' : 'No')}`);
    console.log(`\n💡 Set environment variables:`);
    console.log(`  export AI_PROVIDER=openai  # atau anthropic, ollama`);
    console.log(`  export OPENAI_API_KEY=sk-...`);
    console.log(`  export API_BASE_URL=https://api.openai.com/v1`);
  });

program.parse(process.argv);

if (!process.argv.slice(2).length) {
  program.outputHelp();
}
