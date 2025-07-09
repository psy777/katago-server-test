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

katago.stderr.pipe(process.stderr);

katago.on('exit', (code) => {
  console.log(`[katago process exited with code ${code}]`);
});

let chain = Promise.resolve();

function sendQuery(query) {
  console.log('[SEND]', query);
  katago.stdin.write(query + '\n');
}

function analyze(moves, visits = 100) {
  chain = chain.then(() => new Promise((resolve, reject) => {
    const query = {
      id: `query-${Date.now()}`,
      moves: moves.map((move, i) => [i % 2 === 0 ? 'B' : 'W', move]),
      boardXSize: 19,
      boardYSize: 19,
      maxVisits: visits,
      rules: 'tromp-taylor'
    };
    const queryStr = JSON.stringify(query);
    sendQuery(queryStr);

    const onLine = line => {
      console.log('[RECV]', line);
      try {
        const obj = JSON.parse(line);
        if (obj.id === query.id) {
          rl.removeListener('line', onLine);
          if (obj.error) {
            reject(new Error(obj.error));
          } else {
            resolve(obj);
          }
        }
      } catch (e) {
        // Ignore parse errors, they could be startup messages
      }
    };

    rl.on('line', onLine);
  }));
  return chain;
}

module.exports = { analyze };
