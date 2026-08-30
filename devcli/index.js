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

// Daftar Provider dan Model yang Tersedia
const PROVIDERS = {
  openai: {
    name: 'OpenAI',
    models: [
      'gpt-4o',
      'gpt-4o-mini',
      'gpt-4-turbo',
      'gpt-3.5-turbo',
      'o1-preview',
      'o1-mini'
    ],
    envKey: 'OPENAI_API_KEY',
    defaultUrl: 'https://api.openai.com/v1'
  },
  anthropic: {
    name: 'Anthropic',
    models: [
      'claude-3-5-sonnet-20241022',
      'claude-3-opus-20240229',
      'claude-3-haiku-20240307'
    ],
    envKey: 'ANTHROPIC_API_KEY',
    defaultUrl: 'https://api.anthropic.com'
  },
  google: {
    name: 'Google Gemini',
    models: [
      'gemini-1.5-pro',
      'gemini-1.5-flash'
    ],
    envKey: 'GOOGLE_API_KEY',
    defaultUrl: 'https://generativelanguage.googleapis.com/v1beta'
  },
  groq: {
    name: 'Groq',
    models: [
      'llama-3.1-70b-versatile',
      'llama-3.1-8b-instant',
      'mixtral-8x7b-32768'
    ],
    envKey: 'GROQ_API_KEY',
    defaultUrl: 'https://api.groq.com/openai/v1'
  },
  ollama: {
    name: 'Ollama (Local)',
    models: [], // Akan dideteksi otomatis
    envKey: '',
    defaultUrl: 'http://localhost:11434'
  }
};

// Konfigurasi saat ini
let API_PROVIDER = process.env.AI_PROVIDER || 'openai';
let API_KEY = process.env[PROVIDERS[API_PROVIDER]?.envKey] || '';
let API_BASE_URL = process.env.API_BASE_URL || PROVIDERS[API_PROVIDER]?.defaultUrl;
let AI_MODEL = process.env.AI_MODEL || (API_PROVIDER === 'ollama' ? 'llama3.1' : 'gpt-4o-mini');

// Simple HTTP client untuk call API tanpa dependency tambahan
async function callAPI(messages, model) {
  const isOllama = API_PROVIDER === 'ollama';
  const isAnthropic = API_PROVIDER === 'anthropic';
  
  let url, headers, body;

  if (isOllama) {
    url = 'http://localhost:11434/api/chat';
    headers = { 'Content-Type': 'application/json' };
    body = {
      model: model || 'llama3.1',
      messages: messages,
      stream: false
    };
  } else if (isAnthropic) {
    url = `${API_BASE_URL}/messages`;
    headers = {
      'Content-Type': 'application/json',
      'x-api-key': API_KEY,
      'anthropic-version': '2023-06-01'
    };
    // Anthropic format berbeda
    const systemMsg = messages.find(m => m.role === 'system');
    const chatMsgs = messages.filter(m => m.role !== 'system').map(m => ({
      role: m.role === 'assistant' ? 'assistant' : 'user',
      content: m.content
    }));
    body = {
      model: model || 'claude-3-5-sonnet-20241022',
      max_tokens: 4096,
      system: systemMsg?.content || 'You are a helpful coding assistant.',
      messages: chatMsgs
    };
  } else {
    // OpenAI, Google, Groq (format OpenAI-compatible)
    url = `${API_BASE_URL}/chat/completions`;
    headers = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${API_KEY}`
    };
    body = {
      model: model || 'gpt-4o-mini',
      messages: messages,
      temperature: 0.7
    };
  }

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(body)
    });

    if (!response.ok) {
      const errorData = await response.text();
      throw new Error(`HTTP ${response.status}: ${errorData}`);
    }

    const data = await response.json();
    
    if (isOllama) {
      return data.message.content;
    } else if (isAnthropic) {
      return data.content[0].text;
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
    const response = await callAPI(messages, AI_MODEL);
    
    // Update history (batasi agar tidak terlalu panjang)
    conversationHistory.push({ role: "user", content: prompt });
    conversationHistory.push({ role: "assistant", content: response });
    if (conversationHistory.length > 10) conversationHistory.shift();

    return response;
  } catch (error) {
    let errorMsg = chalk.red(`Error AI: ${error.message}`);
    
    if (!API_KEY && API_PROVIDER !== 'ollama') {
      errorMsg += '\n\n' + chalk.yellow('💡 Tips: Set API key untuk provider yang dipilih.');
      errorMsg += `\n   Export: export ${PROVIDERS[API_PROVIDER]?.envKey}=your-key-here`;
      if (API_PROVIDER === 'ollama') {
        errorMsg += '\n   Atau install Ollama: curl -fsSL https://ollama.com/install.sh | sh';
      }
    }
    
    return errorMsg;
  }
}

// Mode Interaktif (REPL)
async function startInteractiveMode() {
  const providerInfo = PROVIDERS[API_PROVIDER];
  console.log(chalk.blue.bold("\n🚀 DevCLI Mode Interaktif Aktif"));
  console.log(chalk.gray(`Provider: ${chalk.green(providerInfo?.name || API_PROVIDER.toUpperCase())} | Model: ${chalk.cyan(AI_MODEL)}`));
  console.log(chalk.gray("Ketik 'exit' untuk keluar, 'clear' untuk reset chat, 'config' untuk ubah pengaturan.\n"));

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
    if (input.toLowerCase() === 'config') {
      await setupConfig();
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
  .description('Setup konfigurasi AI (provider, model, API key)')
  .option('--show', 'Tampilkan konfigurasi saat ini')
  .action(async (options) => {
    if (options.show) {
      showConfig();
    } else {
      await setupConfig();
    }
  });

// Fungsi untuk menampilkan konfigurasi
function showConfig() {
  const providerInfo = PROVIDERS[API_PROVIDER];
  console.log(chalk.blue.bold("\n📋 DevCLI Configuration:"));
  console.log(`  Provider: ${chalk.green(providerInfo?.name || API_PROVIDER)}`);
  console.log(`  Model: ${chalk.cyan(AI_MODEL)}`);
  console.log(`  API Base URL: ${chalk.green(API_BASE_URL)}`);
  console.log(`  API Key Set: ${chalk.green(API_KEY ? 'Yes (****)' : 'No')}`);
  console.log(`\n💡 Available Providers:`);
  Object.entries(PROVIDERS).forEach(([key, info]) => {
    const isCurrent = key === API_PROVIDER ? chalk.yellow(' (current)') : '';
    console.log(`  - ${key}: ${info.name}${isCurrent}`);
  });
  console.log(`\n💡 Set environment variables:`);
  console.log(`  export AI_PROVIDER=<provider>  # ${Object.keys(PROVIDERS).join(', ')}`);
  console.log(`  export AI_MODEL=<model-name>`);
  console.log(`  export ${providerInfo?.envKey || 'API_KEY'}=<your-key>`);
}

// Fungsi untuk setup konfigurasi interaktif
async function setupConfig() {
  console.log(chalk.blue.bold("\n⚙️  DevCLI Configuration Setup\n"));
  
  // Pilih Provider
  const providerChoices = Object.entries(PROVIDERS).map(([key, info]) => ({
    name: `${info.name} (${key})`,
    value: key
  }));
  
  const { selectedProvider } = await inquirer.prompt([
    {
      type: 'list',
      name: 'selectedProvider',
      message: 'Pilih AI Provider:',
      choices: providerChoices,
      default: API_PROVIDER
    }
  ]);
  
  API_PROVIDER = selectedProvider;
  const providerInfo = PROVIDERS[API_PROVIDER];
  
  // Update env vars sementara
  process.env.AI_PROVIDER = API_PROVIDER;
  API_BASE_URL = providerInfo.defaultUrl;
  process.env.API_BASE_URL = API_BASE_URL;
  
  console.log(chalk.gray(`Provider dipilih: ${providerInfo.name}`));
  
  // Jika bukan Ollama, minta API Key
  if (providerInfo.envKey) {
    const { apiKey } = await inquirer.prompt([
      {
        type: 'input',
        name: 'apiKey',
        message: `Masukkan ${providerInfo.envKey}:`,
        mask: '*',
        validate: (input) => {
          if (input.length < 5) return 'API key terlalu pendek';
          return true;
        }
      }
    ]);
    
    API_KEY = apiKey;
    process.env[providerInfo.envKey] = apiKey;
    console.log(chalk.gray('API key disimpan (sesi ini saja)'));
  }
  
  // Pilih Model
  let availableModels = providerInfo.models;
  
  // Untuk Ollama, coba deteksi model lokal
  if (API_PROVIDER === 'ollama') {
    try {
      const { stdout } = await execPromise('ollama list 2>/dev/null || echo ""');
      if (stdout.trim()) {
        availableModels = stdout.trim().split('\n')
          .filter(line => line.trim())
          .map(line => line.split(/\s+/)[0])
          .filter(name => name && !name.startsWith('NAME'));
      }
      if (availableModels.length === 0) {
        console.log(chalk.yellow('\n⚠️  Tidak ada model Ollama terdeteksi.'));
        console.log(chalk.gray('Jalankan: ollama pull llama3.1'));
        availableModels = ['llama3.1', 'codellama', 'deepseek-coder'];
      }
    } catch (e) {
      console.log(chalk.yellow('\n⚠️  Ollama tidak terdeteksi. Pastikan sudah diinstall.'));
      availableModels = ['llama3.1', 'codellama', 'deepseek-coder'];
    }
  }
  
  const { selectedModel } = await inquirer.prompt([
    {
      type: 'list',
      name: 'selectedModel',
      message: 'Pilih Model:',
      choices: availableModels.map(m => ({ name: m, value: m })),
      default: AI_MODEL
    }
  ]);
  
  AI_MODEL = selectedModel;
  process.env.AI_MODEL = selectedModel;
  
  console.log(chalk.gray(`Model dipilih: ${AI_MODEL}`));
  
  // Simpan ke file .env
  const envContent = `AI_PROVIDER=${API_PROVIDER}\nAI_MODEL=${AI_MODEL}\n${providerInfo.envKey ? `${providerInfo.envKey}=${API_KEY}\n` : ''}API_BASE_URL=${API_BASE_URL}\n`;
  try {
    await fs.writeFile('.env', envContent);
    console.log(chalk.green('\n✅ Konfigurasi disimpan ke file .env'));
  } catch (err) {
    console.log(chalk.yellow('\n⚠️  Gagal menyimpan ke .env, tapi konfigurasi aktif untuk sesi ini.'));
  }
  
  console.log(chalk.cyan('\n💡 Untuk membuat permanen, tambahkan ke ~/.bashrc atau ~/.zshrc:'));
  console.log(chalk.gray(`  export AI_PROVIDER=${API_PROVIDER}`));
  console.log(chalk.gray(`  export AI_MODEL=${AI_MODEL}`));
  if (providerInfo.envKey) {
    console.log(chalk.gray(`  export ${providerInfo.envKey}=...`));
  }
}

program.parse(process.argv);

if (!process.argv.slice(2).length) {
  program.outputHelp();
}
