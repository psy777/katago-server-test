const { spawn } = require('child_process');
const readline = require('readline');
const path = require('path');

const KATAGO_BIN = 'katago'; // uses PATH
const MODEL_PATH = path.resolve(__dirname, '../katago-server/kata1-b28c512nbt-s9584861952-d4960414494.bin');
const CONFIG_PATH = path.resolve(__dirname, '../katago-server/analysis.cfg');

const katago = spawn(KATAGO_BIN, [
  'analysis',
  '-model', MODEL_PATH,
  '-config', CONFIG_PATH
]);

const rl = readline.createInterface({ input: katago.stdout });

let chain = Promise.resolve();

function sendGTP(cmd) {
  console.log('[SEND]', cmd);
  katago.stdin.write(cmd + '\n');
}

function analyze(moves, visits = 100) {
  chain = chain.then(() => new Promise((resolve, reject) => {
    sendGTP('boardsize 19');
    sendGTP('clear_board');
    moves.forEach(m => sendGTP('play ' + m));
    sendGTP(`kata-analyze B ${visits}`);

    const onLine = line => {
      console.log('[RECV]', line);
      if (!line.startsWith('=')) return;
      try {
        const payload = line.slice(1).trim();
        const obj = JSON.parse(payload);
        rl.removeListener('line', onLine);
        resolve(obj);
      } catch (e) {
        console.error('JSON parse failed:', e);
      }
    };

    rl.on('line', onLine);
  }));
  return chain;
}

module.exports = { analyze };
